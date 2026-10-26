/**
 * 故障注入清单（Fault Registry）
 * 用法：URL 上加 ?fault=id1,id2，例如 /?fault=layout-card-overflow#/home
 */

const params = new URLSearchParams(location.search);
const fromUrl = params.get('fault');

if (fromUrl !== null) sessionStorage.setItem('mtct.faults', fromUrl);
const raw = fromUrl ?? sessionStorage.getItem('mtct.faults') ?? '';
const active = new Set(raw.split(',').map((s) => s.trim()).filter(Boolean));

/* ---------- 基准集故障（data/faults.json，120 条） ---------- */

const faultSpecs = Object.create(null);
let specsLoaded = false;

export async function initFaults() {
  if (specsLoaded) return;
  specsLoaded = true;
  if (![...active].some((id) => id.startsWith('bench-'))) return;
  try {
    const res = await fetch('data/faults.json', { cache: 'no-store' });
    if (!res.ok) return;
    const list = await res.json();
    for (const spec of list) faultSpecs[spec.id] = spec;
  } catch (err) {
    console.warn('[mtct] load benchmark faults failed', err);
  }
}

/** 当前页是否有指定动作型故障（console-error / skeleton-stuck / error-state / disable / hide） */
export function hasAction(action, page) {
  for (const id of active) {
    const spec = faultSpecs[id];
    if (!spec) continue;
    if (spec.action === action && (spec.page === page || spec.page === 'all')) return true;
  }
  return false;
}

function kebab(prop) {
  return prop.replace(/[A-Z]/g, (m) => '-' + m.toLowerCase());
}

function applySpecFault(_root, spec) {
  // 基线集的故障可能落在顶栏/body 上，作用域必须是整个文档
  const nodes = [...document.querySelectorAll(spec.selector)];
  for (const el of nodes) {
    if (spec.action === 'disable' && 'disabled' in el) {
      el.disabled = true;
    }
    if (spec.action === 'hide') {
      el.style.setProperty('display', 'none', 'important');
    }
    for (const [prop, value] of Object.entries(spec.styles || {})) {
      el.style.setProperty(kebab(prop), value, 'important');
    }
  }
}


const FAULTS = {
  'layout-card-overflow': {
    page: 'home', category: 'layout', severity: 'major', detector: 'layout',
    description: '行情卡片固定 372px 宽并禁止换行，1366 宽下撑破网格容器',
    apply(root) {
      root.querySelectorAll('.market-card').forEach((el) => el.classList.add('f-card-overflow'));
    },
  },
  'layout-btn-overlap': {
    page: 'trade', category: 'layout', severity: 'blocker', detector: 'layout',
    description: '下单按钮上移 38px，压住数量输入区',
    apply(root) {
      const el = root.querySelector('.trade-submit');
      if (el) el.classList.add('f-btn-overlap');
    },
  },
  'layout-label-overlap': {
    page: 'kyc', category: 'layout', severity: 'major', detector: 'layout',
    description: 'KYC 表单项 label 下移压住输入框',
    apply(root) {
      root.querySelectorAll('.kyc-card .field label').forEach((el) => el.classList.add('f-label-overlap'));
    },
  },
  'i18n-btn-truncate': {
    page: 'coin', category: 'i18n', severity: 'major', detector: 'layout',
    description: '币种页买入/卖出按钮宽度锁死 92px，越南语长文案被硬切',
    apply(root) {
      root.querySelectorAll('.coin-actions .btn').forEach((el) => el.classList.add('f-truncate'));
    },
  },
  'i18n-pair-truncate': {
    page: 'home', category: 'i18n', severity: 'minor', detector: 'layout',
    description: '交易对名称限宽 104px 且单行，长名称被截断',
    apply(root) {
      root.querySelectorAll('.market-card .pair').forEach((el) => el.classList.add('f-truncate-title'));
    },
  },
  'i18n-address-truncate': {
    page: 'kyc', category: 'i18n', severity: 'major', detector: 'layout',
    description: '地址输入框宽度锁死 140px，长地址不可见',
    apply(root) {
      const el = root.querySelector('.kyc-address');
      if (el) el.classList.add('f-truncate-wide');
    },
  },
  'vi-clip-price': {
    page: 'home', category: 'vi', severity: 'major', detector: 'visual',
    description: '行情卡价格行高 0.88 + 固定高度，越南语叠音符号被裁切',
    apply(root) {
      root.querySelectorAll('.market-card .price').forEach((el) => el.classList.add('f-vi-clip'));
    },
  },
  'vi-clip-stat': {
    page: 'coin', category: 'vi', severity: 'major', detector: 'visual',
    description: '统计标签行高 0.8，变音符号上下被裁',
    apply(root) {
      root.querySelectorAll('.stat-label').forEach((el) => el.classList.add('f-vi-clip-sm'));
    },
  },
  'vi-clip-btn': {
    page: 'trade', category: 'vi', severity: 'blocker', detector: 'visual',
    description: '下单按钮文字被高度裁切，只剩半行',
    apply(root) {
      const el = root.querySelector('.trade-submit');
      if (el) el.classList.add('f-vi-clip');
    },
  },
  'zoom-trade-nostack': {
    page: 'trade', category: 'zoom', severity: 'blocker', detector: 'layout',
    description: '交易页两栏不响应断点，150% 缩放时横向溢出',
    apply(root) {
      const el = root.querySelector('.trade-layout');
      if (el) el.classList.add('f-no-stack');
    },
  },
  'zoom-grid-fixed': {
    page: 'home', category: 'zoom', severity: 'major', detector: 'layout',
    description: '行情网格固定 4 列 × 260px，窄视口下溢出',
    apply(root) {
      const el = root.querySelector('.market-grid');
      if (el) el.classList.add('f-grid-fixed');
    },
  },
  'zoom-login-fixed': {
    page: 'login', category: 'zoom', severity: 'major', detector: 'layout',
    description: '登录卡片固定 980px 宽，窄视口下溢出',
    apply(root) {
      const el = root.querySelector('.login-card');
      if (el) el.classList.add('f-fixed-card');
    },
  },
  'contrast-change': {
    page: 'home', category: 'contrast', severity: 'major', detector: 'rule',
    description: '涨跌幅徽标前景色对比度约 1.6:1，低于 WCAG AA',
    apply(root) {
      root.querySelectorAll('.market-card .change').forEach((el) => el.classList.add('f-contrast-low'));
    },
  },
  'contrast-label': {
    page: 'kyc', category: 'contrast', severity: 'major', detector: 'rule',
    description: 'KYC 表单 label 颜色对比度不足',
    apply(root) {
      root.querySelectorAll('.kyc-card .field label').forEach((el) => el.classList.add('f-contrast-low'));
    },
  },
  'contrast-nav': {
    page: 'all', category: 'contrast', severity: 'minor', detector: 'rule',
    description: '顶部导航文字对比度不足',
    apply(root) {
      root.querySelectorAll('.topbar .nav a').forEach((el) => el.classList.add('f-contrast-low'));
    },
  },
  'font-mono-price': {
    page: 'coin', category: 'font', severity: 'minor', detector: 'visual',
    description: '主价格换成等宽字体，字宽变化导致数字与徽标错位',
    apply(root) {
      const el = root.querySelector('.price-big');
      if (el) el.classList.add('f-font-mono');
    },
  },
  'font-tab-big': {
    page: 'home', category: 'font', severity: 'major', detector: 'layout',
    description: 'Tab 字号放大 1.5 倍，越南语下 Tab 换行错位',
    apply(root) {
      root.querySelectorAll('.tab-btn').forEach((el) => el.classList.add('f-font-big'));
    },
  },
  'font-small-label': {
    page: 'settings', category: 'font', severity: 'minor', detector: 'visual',
    description: '设置项说明文字缩到 10px，几乎不可读',
    apply(root) {
      root.querySelectorAll('.setting-desc').forEach((el) => el.classList.add('f-font-small'));
    },
  },
  'functional-api-error-silent': {
    page: 'home', category: 'functional', severity: 'blocker', detector: 'functional',
    description: '行情接口失败时静默展示空列表，不显示错误态与重试入口',
  },
  'functional-skeleton-stuck': {
    page: 'home', category: 'loading', severity: 'blocker', detector: 'visual',
    description: '骨架屏永不消失，数据加载完成后仍停留在加载态',
  },
  'functional-btn-disabled': {
    page: 'login', category: 'functional', severity: 'blocker', detector: 'functional',
    description: '登录按钮始终 disabled，用户无法提交',
  },
  'functional-console-error': {
    page: 'all', category: 'functional', severity: 'major', detector: 'functional',
    description: '页面渲染后抛出未捕获异常（控制台报错）',
  },
};

export function has(id) {
  return active.has(id);
}

export function activeFaults() {
  return [...active];
}

export function applyAfterRender(root, page) {
  for (const id of active) {
    const fault = FAULTS[id];
    if (!fault) {
      console.warn(`[mtct] unknown fault: ${id}`);
      continue;
    }
    if (fault.page !== 'all' && fault.page !== page) continue;
    try {
      fault.apply?.(root, page);
    } catch (err) {
      console.warn(`[mtct] fault apply failed: ${id}`, err);
    }
  }

  /* 基准集规格故障：按 JSON 的 selector + styles / action 注入 */
  for (const id of active) {
    const spec = faultSpecs[id];
    if (!spec) continue;
    if (spec.page !== 'all' && spec.page !== page) continue;
    try {
      applySpecFault(root, spec);
    } catch (err) {
      console.warn(`[mtct] spec fault apply failed: ${id}`, err);
    }
  }
}

export function faultManifest() {
  return Object.entries(FAULTS).map(([id, f]) => ({
    id, page: f.page, category: f.category, severity: f.severity, detector: f.detector, description: f.description,
  }));
}

export function isDebug() {
  return new URLSearchParams(location.search).get('debug') === '1';
}

export function renderFaultBanner() {
  const el = document.getElementById('fault-banner');
  if (!el) return;
  if (!isDebug() || active.size === 0) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.textContent = `FAULTS: ${[...active].join(', ')}`;
}

window.__MTCT_FAULT_MANIFEST__ = faultManifest();
window.__MTCT_FAULT_IDS__ = activeFaults();
