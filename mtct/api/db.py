"""SQLite 持久化：runs / run_cases。

刻意不用 ORM：4 周项目里，手写 SQL + 薄仓储更容易讲清楚
"状态机 / 幂等键 / 增量落库"这三件事，也少一层依赖。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id               TEXT PRIMARY KEY,
    status           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    started_at       TEXT,
    finished_at      TEXT,
    request_json     TEXT NOT NULL,
    idempotency_key  TEXT UNIQUE,
    total            INTEGER NOT NULL DEFAULT 0,
    passed           INTEGER NOT NULL DEFAULT 0,
    failed           INTEGER NOT NULL DEFAULT 0,
    errors           INTEGER NOT NULL DEFAULT 0,
    report_path      TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run_cases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    case_key        TEXT NOT NULL,
    case_name       TEXT NOT NULL DEFAULT '',
    terminal_id     TEXT NOT NULL,
    fault           TEXT NOT NULL,
    status          TEXT NOT NULL,
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    failed_rules    TEXT NOT NULL DEFAULT '',
    error           TEXT,
    assertions_json TEXT NOT NULL DEFAULT '[]',
    triage_json     TEXT,
    screenshot      TEXT,
    UNIQUE(run_id, case_key, terminal_id, fault)
);

CREATE INDEX IF NOT EXISTS idx_run_cases_run ON run_cases(run_id);

CREATE TABLE IF NOT EXISTS clusters (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL,
    cluster_key    TEXT NOT NULL,
    label          TEXT NOT NULL,
    root_cause     TEXT NOT NULL,
    rule           TEXT NOT NULL DEFAULT '',
    page           TEXT NOT NULL DEFAULT '',
    selector       TEXT NOT NULL DEFAULT '',
    terminals_json TEXT NOT NULL DEFAULT '[]',
    member_count   INTEGER NOT NULL DEFAULT 0,
    sample_message TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    UNIQUE(run_id, cluster_key)
);

CREATE INDEX IF NOT EXISTS idx_clusters_run ON clusters(run_id);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(runs)")}
        for name, ddl in (
            ("clusters_count", "INTEGER NOT NULL DEFAULT 0"),
            ("cluster_metrics_json", "TEXT"),
        ):
            if name not in columns:
                self._conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {ddl}")
        self._conn.commit()

    # ---------- runs ----------

    def create_run(self, run_id: str, request: dict[str, Any],
                   idempotency_key: str | None, created_at: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs (id, status, created_at, request_json, idempotency_key)"
                " VALUES (?, 'queued', ?, ?, ?)",
                (run_id, created_at, json.dumps(request, ensure_ascii=False), idempotency_key),
            )
            self._conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def get_run_by_idempotency(self, key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE idempotency_key = ?", (key,)
        ).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_started(self, run_id: str, started_at: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET status='running', started_at=? WHERE id=?",
                (started_at, run_id),
            )
            self._conn.commit()

    def finish_run(self, run_id: str, status: str, finished_at: str,
                   total: int, passed: int, failed: int, errors: int,
                   report_path: str | None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET status=?, finished_at=?, total=?, passed=?,"
                " failed=?, errors=?, report_path=? WHERE id=?",
                (status, finished_at, total, passed, failed, errors, report_path, run_id),
            )
            self._conn.commit()

    def request_cancel(self, run_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,)
            )
            self._conn.commit()

    def cancel_requested(self, run_id: str) -> bool:
        row = self._conn.execute(
            "SELECT cancel_requested FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        return bool(row and row["cancel_requested"])

    # ---------- run_cases ----------

    def upsert_case_result(self, run_id: str, result) -> None:
        failed_rules = ",".join(a.rule for a in result.assertions if not a.passed)
        with self._lock:
            self._conn.execute(
                """INSERT INTO run_cases (run_id, case_key, case_name, terminal_id, fault,
                       status, duration_ms, failed_rules, error, assertions_json,
                       triage_json, screenshot)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, case_key, terminal_id, fault) DO UPDATE SET
                       status=excluded.status, duration_ms=excluded.duration_ms,
                       failed_rules=excluded.failed_rules, error=excluded.error,
                       assertions_json=excluded.assertions_json,
                       triage_json=excluded.triage_json, screenshot=excluded.screenshot""",
                (
                    run_id, result.case_key, result.case_name, result.terminal_id,
                    result.fault, result.status, result.duration_ms, failed_rules,
                    result.error,
                    json.dumps([a.__dict__ for a in result.assertions], ensure_ascii=False),
                    json.dumps(result.triage, ensure_ascii=False) if result.triage else None,
                    result.screenshot,
                ),
            )
            self._conn.commit()

    def list_case_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM run_cases WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["assertions"] = json.loads(item.pop("assertions_json") or "[]")
            item["triage"] = json.loads(item.pop("triage_json")) if item.get("triage_json") else None
            out.append(item)
        return out

    # ---------- clusters ----------

    def save_clusters(self, run_id: str, clusters: list[dict], metrics: dict) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM clusters WHERE run_id=?", (run_id,))
            for cluster in clusters:
                self._conn.execute(
                    "INSERT INTO clusters (run_id, cluster_key, label, root_cause, rule, page,"
                    " selector, terminals_json, member_count, sample_message, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        cluster["cluster_id"],
                        cluster["label"],
                        cluster["root_cause"],
                        cluster.get("rule", ""),
                        cluster.get("page", ""),
                        cluster.get("selector", ""),
                        json.dumps(cluster.get("terminals", []), ensure_ascii=False),
                        cluster.get("member_count", 0),
                        cluster.get("sample_message", ""),
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
            self._conn.execute(
                "UPDATE runs SET clusters_count=?, cluster_metrics_json=? WHERE id=?",
                (len(clusters), json.dumps(metrics, ensure_ascii=False), run_id),
            )
            self._conn.commit()

    def list_clusters(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM clusters WHERE run_id=? ORDER BY member_count DESC", (run_id,)
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["terminals"] = json.loads(item.pop("terminals_json") or "[]")
            item["members"] = []
            out.append(item)
        return out