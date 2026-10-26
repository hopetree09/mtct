/* MTCT 控制台：零构建 SPA（hash 路由 + 原生 DOM） */

const appEl = document.getElementById('app');
const drawerEl = document.getElementById('drawer');

let currentRun = null;
let refreshTimer = null;

const STATUS_TEXT = {
  passed: '通过', failed: '不通过', error: '异常',
  queued: '排队中', running: '执行中', finished: '已完成',
  cancelled: '已取消',
};

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[ch]));

const shortTerminal = (id) => String(id || '').replace(/^chromium-/, '');

async function api(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${path} -> HTTP ${response.status}`);
  return response.json();
}

function badge(status) {
  return `<span class="badge ${esc(status)}">${STATUS_TEXT[status] || esc(status)}</span>`;
}

function route() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [name = 'runs', id = ''] = raw.split('/');
  return { name, id };
}

async function render() {
  window.clearTimeout(refreshTimer);
  const { name, id } = route();
  try {
    if (name === 'run' && id) await renderRun(id);
    else await renderRuns();
  } catch (error) {
    appEl.innerHTML = `<div class="empty">加载失败：${esc(error.message)}</div>`;
  }
}

/* ---------------- 执行记录 ---------------- */

async function renderRuns() {
  document.title = 'MTCT · 执行记录';
  const runs = await api('/api/runs');
  const rows = runs.map((run) => `
    <tr>
      <td><a class="mono" href="#/run/${encodeURIComponent(run.id)}">${esc(run.id)}</a></td>
      <td>${badge(run.status)}</td>
      <td>${run.total}</td>
      <td>${run.passed}</td>
      <td>${run.failed}</td>
      <td>${run.errors}</td>
      <td class="mono">${esc(run.created_at)}</td>
      <td>
        ${run.report_url ? `<a href="${run.report_url}" target="_blank" rel="noreferrer">报告</a>` : '<span class="sub">-</span>'}
      </td>
    </tr>`).join('');

  appEl.innerHTML = `
    <div class="page-head">
      <h1>执行记录</h1>
      <span class="sub">共 ${runs.length} 轮 · 点击 Run ID 查看矩阵与证据</span>
    </div>
    ${runs.length ? `<table>
      <thead><tr><th>Run</th><th>状态</th><th>总数</th><th>通过</th><th>不通过</th>
      <th>异常</th><th>创建时间</th><th>报告</th></tr></thead>
      <tbody>${rows}</tbody></table>` : '<div class="empty">还没有 Run。用 POST /api/runs 提交一轮。</div>'}`;
}

/* ---------------- Run 详情 ---------------- */

async function renderRun(id) {
  const [run, clusters] = await Promise.all([
    api(`/api/runs/${encodeURIComponent(id)}`),
    api(`/api/runs/${encodeURIComponent(id)}/clusters`).catch(() => ({ metrics: {}, clusters: [] })),
  ]);
  currentRun = run;
  document.title = `MTCT · ${run.id}`;

  const cells = run.cases || [];
  const columns = [...new Set(cells.map((item) => item.case_key))];
  const rowMap = new Map();
  for (const item of cells) {
    const key = `${item.terminal_id}||${item.fault}`;
    if (!rowMap.has(key)) rowMap.set(key, { terminal: item.terminal_id, fault: item.fault, map: new Map() });
    rowMap.get(key).map.set(item.case_key, item);
  }
  const rows = [...rowMap.values()];

  const matrixRows = rows.map((row) => `
    <tr>
      <td class="row-label"><strong>${esc(shortTerminal(row.terminal))}</strong><br/>${esc(row.fault)}</td>
      ${columns.map((column) => {
        const item = row.map.get(column);
        if (!item) return '<td><span class="sub">-</span></td>';
        const symbol = item.status === 'passed' ? '✓' : item.status === 'failed' ? '✕' : '!';
        return `<td><div class="cell ${esc(item.status)}"
          data-case="${esc(item.case_key)}"
          data-terminal="${esc(item.terminal_id)}"
          data-fault="${esc(item.fault)}">${symbol}</div></td>`;
      }).join('')}
    </tr>`).join('');

  const clusterCards = (clusters.clusters || []).map((cluster) => `
    <div class="cluster">
      <h3>${esc(cluster.label)}</h3>
      <div class="count">${cluster.member_count} 条失败 · 规则 ${esc(cluster.rule || '-')}</div>
      <div class="root">${esc(cluster.root_cause)}</div>
      <div class="terms">${(cluster.terminals || []).map((t) => `<span class="chip">${esc(shortTerminal(t))}</span>`).join('')}</div>
    </div>`).join('');

  const metrics = clusters.metrics || {};
  const metricText = metrics.failures
    ? `失败 ${metrics.failures} 条 → 根因簇 ${metrics.clusters} 个 · 压缩比 ${metrics.compression}:1`
      + (metrics.ari_vs_fault != null ? ` · ARI ${metrics.ari_vs_fault}` : '')
    : '暂无可聚类的失败';

  appEl.innerHTML = `
    <div class="page-head">
      <h1>Run ${esc(run.id)}</h1>
      ${badge(run.status)}
      <span class="sub">${(run.request.cases || []).length} 条用例 · ${(run.request.terminals || []).join(', ')} · ${(run.request.faults || []).length} 种故障</span>
      <span class="sub" style="margin-left:auto">${run.report_url ? `<a href="${run.report_url}" target="_blank" rel="noreferrer">HTML 报告</a>` : ''}</span>
    </div>
    <div class="cards">
      <div class="card"><div class="k">执行总数</div><div class="v">${run.total}</div></div>
      <div class="card"><div class="k">通过</div><div class="v" style="color:var(--pass)">${run.passed}</div></div>
      <div class="card"><div class="k">不通过</div><div class="v" style="color:var(--fail)">${run.failed}</div></div>
      <div class="card"><div class="k">执行异常</div><div class="v" style="color:var(--err)">${run.errors}</div></div>
      <div class="card"><div class="k">根因簇</div><div class="v">${(clusters.clusters || []).length}</div></div>
    </div>

    <div class="panel">
      <h2>终端 × 用例 矩阵</h2>
      <div class="matrix"><table>
        <thead><tr><th>终端 / 故障</th>${columns.map((c) => `<th class="rot">${esc(c)}</th>`).join('')}</tr></thead>
        <tbody>${matrixRows}</tbody>
      </table></div>
      <div class="sub" style="margin-top:8px">点击色块查看断言明细与证据截图</div>
    </div>

    <div class="panel">
      <h2>根因簇</h2>
      <div class="sub" style="margin-bottom:12px">${esc(metricText)}</div>
      ${clusterCards ? `<div class="cluster-grid">${clusterCards}</div>` : '<div class="empty">本轮没有失败用例，无需归因</div>'}
    </div>`;

  if (run.status === 'queued' || run.status === 'running') {
    refreshTimer = window.setTimeout(() => renderRun(id), 2500);
  }
}

/* ---------------- 用例详情抽屉 ---------------- */

function openCase(item) {
  const artifacts = item.artifacts || {};
  const assertions = (item.assertions || []).map((assertion) => `
    <div class="assert ${assertion.passed ? 'pass' : 'fail'}">
      <div class="rule">${esc(assertion.rule)} · ${esc(assertion.target || '')}</div>
      ${assertion.message ? `<div class="msg">${esc(assertion.message)}</div>` : ''}
    </div>`).join('');

  const shots = [
    ['实际截图', artifacts.actual],
    ['基线截图', artifacts.baseline],
    ['差异可视化', artifacts.diff],
    ['变化区域裁片', artifacts.crop],
  ].filter(([, url]) => url);

  drawerEl.classList.remove('hidden');
  drawerEl.innerHTML = `
    <div class="drawer-head">
      <div>
        <h2>${esc(item.case_name || item.case_key)}</h2>
        <div class="sub mono">${esc(item.terminal_id)} · ${esc(item.fault)} · ${item.duration_ms}ms</div>
      </div>
      <button class="drawer-close" id="close-drawer">关闭</button>
    </div>
    <div style="margin-bottom:14px">
      ${badge(item.status)}
      ${item.failed_rules ? `<span class="sub">失败规则：${esc(item.failed_rules)}</span>` : ''}
    </div>
    ${item.error ? `<div class="assert fail"><div class="msg">${esc(item.error)}</div></div>` : ''}
    <h2>断言明细</h2>
    ${assertions || '<div class="empty">没有断言记录</div>'}
    ${item.triage ? `
      <div class="assert"><div class="rule">AI 判定 · ${esc(item.triage.model || '')}</div>
        <div class="msg">${esc(item.triage.verdict)}：${esc(item.triage.reason)}</div></div>` : ''}
    <h2 style="margin-top:18px">证据</h2>
    ${shots.length ? `<div class="shots">${shots.map(([caption, url]) => `
      <div class="shot"><div class="cap">${caption}</div>
        <img src="${url}" loading="lazy" alt="${caption}" /></div>`).join('')}</div>`
      : '<div class="empty">没有可展示的图片</div>'}`;

  document.getElementById('close-drawer').onclick = () => drawerEl.classList.add('hidden');
}

appEl.addEventListener('click', (event) => {
  const cell = event.target.closest('.cell');
  if (!cell || !currentRun) return;
  const item = (currentRun.cases || []).find((candidate) =>
    candidate.case_key === cell.dataset.case
    && candidate.terminal_id === cell.dataset.terminal
    && candidate.fault === cell.dataset.fault);
  if (item) openCase(item);
});

drawerEl.addEventListener('click', (event) => {
  if (event.target === drawerEl) drawerEl.classList.add('hidden');
});

window.addEventListener('hashchange', render);
render();