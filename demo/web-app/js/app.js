/**
 * DemoX Exchange — 演示站主逻辑（无框架、无构建步骤）
 * 这是"被测对象"：像真实应用一样渲染、路由、加载数据，
 * 同时具备可测性钩子（testid、就绪标记、故障开关）。
 */

import { initLocale, loadLocale, applyI18n, t, getLocale, LANG_KEY } from './i18n.js';
import { fetchMarkets } from './data.js';
import { has, hasAction, initFaults, applyAfterRender, renderFaultBanner, activeFaults } from './faults.js';

const appEl = document.getElementById('app');
const langBadge = document.getElementById('lang-badge');

const state = {
  tab: 'all',
  search: '',
  theme: localStorage.getItem('mtct.theme') || 'light',
  notify: localStorage.getItem('mtct.notify') === '1',
};

let markets = null;
let currentPage = 'home';
const favSet = new Set(JSON.parse(localStorage.getItem('mtct.fav') || '[]'));

/* 就绪标记：测试必须等到这两个信号都出现才能截图 */
function setReady(value) {
  window.__MTCT_READY__ = value;
  document.documentElement.dataset.mtctReady = value ? '1' : '0';
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
}

function fmt(num, digits = 2) {
  try {
    return new Intl.NumberFormat(getLocale(), {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(num);
  } catch {
    return Number(num).toFixed(digits);
  }
}

function money(num) {
  return `$${fmt(num, 2)}`;
}

function pct(num) {
  return `${num >= 0 ? '+' : ''}${fmt(num, 2)}%`;
}

/** 确定性走势图：同一个 seed 永远画出同一张图，避免截图抖动 */
function sparkline(seed, up, cls = 'spark') {
  let s = seed || 7;
  const rnd = () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
  let v = 50;
  const points = [];
  for (let i = 0; i < 40; i += 1) {
    v = Math.max(8, Math.min(92, v + (rnd() - 0.5) * 9));
    points.push([i * (100 / 39), v]);
  }
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(' ');
  const color = up ? 'var(--up)' : 'var(--down)';
  return `<svg class="${cls}" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
    <path d="${d}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke" />
  </svg>`;
}

function skeleton() {
  return `<div class="skeleton" data-testid="skeleton" aria-busy="true">
    <div class="sk-line w40"></div>
    <div class="sk-line w70"></div>
    <div class="sk-grid">${'<div class="sk-card"></div>'.repeat(6)}</div>
  </div>`;
}

function stateBlock(title, desc, withRetry) {
  return `<div class="state-block" data-testid="state-block">
    <div class="state-title">${escapeHtml(title)}</div>
    ${desc ? `<div class="state-desc">${escapeHtml(desc)}</div>` : ''}
    ${withRetry ? `<button class="btn btn-primary" type="button" data-action="reload">${t('common.retry')}</button>` : ''}
  </div>`;
}

function emptyBlock() {
  return `<div class="state-block" data-testid="state-block">
    <div class="state-title">${t('home.empty')}</div>
  </div>`;
}

async function ensureMarkets() {
  if (has('functional-api-error-silent') || hasAction('error-state', currentPage)) {
    throw new Error('injected api failure');
  }
  if (!markets) markets = await fetchMarkets();
  return markets;
}

function findCoin(symbol) {
  const list = markets || [];
  return list.find((c) => c.symbol === symbol) || list[0] || null;
}

function filteredMarkets() {
  const q = state.search.trim().toLowerCase();
  return (markets || []).filter((c) => {
    const name = (c.names[getLocale()] || '').toLowerCase();
    const hit = !q || c.pair.toLowerCase().includes(q) || name.includes(q);
    const fav = state.tab !== 'fav' || favSet.has(c.symbol);
    return hit && fav;
  });
}

function marketCard(c) {
  const up = c.change24h >= 0;
  const name = c.names[getLocale()] || c.symbol;
  return `<a class="market-card" href="#/coin/${c.symbol}" data-testid="market-card" data-symbol="${c.symbol}">
    <div class="market-card-head">
      <img class="coin-logo" src="assets/coin.svg" alt="" width="28" height="28" />
      <div style="min-width:0">
        <div class="pair" data-testid="pair">${c.pair}</div>
        <div class="coin-name">${escapeHtml(name)}</div>
      </div>
    </div>
    <div class="price" data-testid="price">${money(c.price)}</div>
    <span class="change ${up ? 'up' : 'down'}" data-testid="change">${pct(c.change24h)}</span>
    ${sparkline(c.seed, up)}
    <div class="meta"><span>${t('home.volume')}</span><span>${money(c.volume24h)}</span></div>
  </a>`;
}

function homeHtml() {
  const list = filteredMarkets();
  const tabBtn = (tab, label) =>
    `<button class="tab-btn ${state.tab === tab ? 'is-active' : ''}" type="button"
      data-action="tab" data-tab="${tab}" data-testid="tab-${tab}">${label}</button>`;
  return `
    <div class="page-head">
      <h1>${t('home.title')}</h1>
      <span class="page-sub">${t('home.sub', { count: (markets || []).length })}</span>
    </div>
    <div class="toolbar">
      <div class="search-box">
        <input id="search" data-testid="search" type="search"
          value="${escapeHtml(state.search)}" placeholder="${t('home.placeholder')}" />
      </div>
      <div class="tabs" data-testid="tabs">
        ${tabBtn('all', t('home.tabAll'))}
        ${tabBtn('fav', t('home.tabFav'))}
      </div>
    </div>
    <div id="market-grid-wrap">
      ${list.length
        ? `<div class="market-grid" data-testid="market-grid">${list.map(marketCard).join('')}</div>`
        : emptyBlock()}
    </div>`;
}

function refreshGrid() {
  const wrap = document.getElementById('market-grid-wrap');
  if (!wrap) {
    render();
    return;
  }
  const list = filteredMarkets();
  wrap.innerHTML = list.length
    ? `<div class="market-grid" data-testid="market-grid">${list.map(marketCard).join('')}</div>`
    : emptyBlock();
  applyAfterRender(wrap, 'home');
}

function loginHtml() {
  return `<div class="auth-wrap">
    <form class="login-card" data-testid="login-card">
      <h1>${t('login.title')}</h1>
      <div class="login-sub">${t('login.subtitle')}</div>
      <div id="login-message" data-testid="login-message"></div>
      <div class="field">
        <label for="email">${t('login.email')}</label>
        <input id="email" data-testid="login-email" type="email" autocomplete="username" placeholder="demo@example.com" />
      </div>
      <div class="field">
        <label for="password">${t('login.password')}</label>
        <input id="password" data-testid="login-password" type="password" autocomplete="current-password" placeholder="••••••••" />
      </div>
      <div class="login-actions">
        <button class="btn btn-primary" type="button" data-action="login" data-testid="login-submit"
          ${has('functional-btn-disabled') ? 'disabled' : ''}>${t('login.submit')}</button>
        <a href="#/login">${t('login.forgot')}</a>
      </div>
    </form>
  </div>`;
}

function coinHtml(c) {
  const up = c.change24h >= 0;
  const name = c.names[getLocale()] || c.symbol;
  const stat = (label, value) =>
    `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}</div></div>`;
  return `
    <div class="page-head">
      <h1 data-testid="coin-title">${c.pair}</h1>
      <span class="page-sub">${escapeHtml(name)}</span>
    </div>
    <div class="coin-header">
      <div class="price-big" data-testid="price-big">${money(c.price)}</div>
      <span class="change ${up ? 'up' : 'down'}" data-testid="change-badge">${pct(c.change24h)}</span>
    </div>
    <div class="coin-stats" data-testid="coin-stats">
      ${stat(t('coin.high'), money(c.high24h))}
      ${stat(t('coin.low'), money(c.low24h))}
      ${stat(t('coin.volume'), money(c.volume24h))}
    </div>
    <div class="panel">
      <h2>${t('coin.chart')}</h2>
      ${sparkline(c.seed, up, 'coin-chart')}
      <div class="coin-actions">
        <button class="btn btn-buy" type="button" data-action="go-trade" data-symbol="${c.symbol}" data-testid="btn-buy">${t('coin.buy', { symbol: c.symbol })}</button>
        <button class="btn btn-sell" type="button" data-action="go-trade" data-symbol="${c.symbol}" data-testid="btn-sell">${t('coin.sell', { symbol: c.symbol })}</button>
      </div>
    </div>`;
}

function orderbookRows(c) {
  const rows = [{ head: true, price: t('trade.price'), amount: t('trade.amount'), total: t('trade.total') }];
  for (let i = 4; i >= 1; i -= 1) {
    const p = c.price * (1 + i * 0.0012);
    const a = 0.5 * i + 0.12;
    rows.push({ price: fmt(p, 2), amount: fmt(a, 3), total: money(p * a), side: 'sell' });
  }
  for (let i = 1; i <= 4; i += 1) {
    const p = c.price * (1 - i * 0.0012);
    const a = 0.4 * i + 0.21;
    rows.push({ price: fmt(p, 2), amount: fmt(a, 3), total: money(p * a), side: 'buy' });
  }
  return rows.map((r) => `<div class="ob-row${r.head ? ' head' : ''}">
      <span class="${r.side === 'buy' ? 'price-buy' : r.side === 'sell' ? 'price-sell' : ''}">${r.price}</span>
      <span>${r.amount}</span>
      <span>${r.total}</span>
    </div>`).join('');
}

function tradeHtml(c) {
  const percentBtn = (p) => `<button class="percent-btn" type="button" data-action="percent" data-percent="${p}">${p}</button>`;
  return `
    <div class="page-head">
      <h1 data-testid="trade-pair">${c.pair}</h1>
      <span class="page-sub">${t('trade.limit')} · ${t('trade.available')} ${money(12500)}</span>
    </div>
    <div class="trade-layout" data-testid="trade-layout">
      <div class="panel">
        <h2>${t('trade.orderbook')}</h2>
        <div class="orderbook" data-testid="orderbook">${orderbookRows(c)}</div>
      </div>
      <div class="panel trade-panel" data-testid="trade-panel">
        <div class="order-tabs">
          <button class="tab-btn is-active" type="button" data-action="noop">${t('trade.limit')}</button>
          <button class="tab-btn" type="button" data-action="noop">${t('trade.market')}</button>
        </div>
        <div class="order-input-row">
          <div class="field">
            <label for="order-price">${t('trade.price')}</label>
            <input id="order-price" data-testid="order-price" type="text" value="${fmt(c.price, 2)}" placeholder="${t('trade.pricePlaceholder')}" />
          </div>
          <div class="field">
            <label for="order-amount">${t('trade.amount')}</label>
            <input id="order-amount" data-testid="order-amount" type="text" placeholder="${t('trade.amountPlaceholder')}" />
          </div>
        </div>
        <div class="percent-row">
          ${['25%', '50%', '75%', '100%'].map(percentBtn).join('')}
        </div>
        <div class="trade-total"><span>${t('trade.total')}</span><span data-testid="order-total">$0.00</span></div>
        <button class="btn btn-primary trade-submit" type="button" data-action="trade-submit"
          data-symbol="${c.symbol}" data-testid="trade-submit">${t('trade.submitBuy', { symbol: c.symbol })}</button>
        <div class="hint">${t('trade.hint')}</div>
      </div>
    </div>`;
}

function kycHtml() {
  return `
    <div class="page-head">
      <h1>${t('kyc.title')}</h1>
      <span class="page-sub">${t('kyc.sub')}</span>
    </div>
    <form class="kyc-card" data-testid="kyc-form">
      <div id="kyc-message" data-testid="kyc-message"></div>
      <div class="field">
        <label for="kyc-name">${t('kyc.name')}</label>
        <input id="kyc-name" data-testid="kyc-name" type="text" />
      </div>
      <div class="field-row">
        <div class="field">
          <label for="kyc-doctype">${t('kyc.docType')}</label>
          <select id="kyc-doctype" data-testid="kyc-doctype">
            <option>${t('kyc.idCard')}</option>
            <option>${t('kyc.passport')}</option>
            <option>${t('kyc.driver')}</option>
          </select>
        </div>
        <div class="field">
          <label for="kyc-docno">${t('kyc.docNo')}</label>
          <input id="kyc-docno" data-testid="kyc-docno" type="text" />
        </div>
      </div>
      <div class="field">
        <label for="kyc-address">${t('kyc.address')}</label>
        <textarea id="kyc-address" class="kyc-address" data-testid="kyc-address" rows="2"
          placeholder="${t('kyc.addressPlaceholder')}"></textarea>
      </div>
      <div class="upload-box" data-testid="kyc-upload">${t('kyc.upload')}</div>
      <button class="btn btn-primary" type="button" data-action="kyc-submit" data-testid="kyc-submit">${t('kyc.submit')}</button>
    </form>`;
}

function settingsHtml() {
  const lang = getLocale();
  const langButtons = ['zh-CN', 'en-US', 'vi-VN'].map((l) =>
    `<button type="button" class="${l === lang ? 'is-active' : ''}"
      data-action="set-lang" data-lang="${l}" data-testid="lang-${l}">${t(`lang.${LANG_KEY[l]}`)}</button>`
  ).join('');
  return `
    <div class="page-head">
      <h1>${t('settings.title')}</h1>
      <span class="page-sub">${t('settings.sub')}</span>
    </div>
    <div class="settings-card" data-testid="settings-card">
      <div class="setting-row">
        <div class="setting-label">${t('settings.language')}</div>
        <div class="setting-control"><div class="seg" data-testid="lang-seg">${langButtons}</div></div>
      </div>
      <div class="setting-row">
        <div class="setting-label">${t('settings.theme')}</div>
        <div class="setting-control">
          <div class="seg">
            <button type="button" class="${state.theme === 'light' ? 'is-active' : ''}"
              data-action="set-theme" data-theme="light" data-testid="theme-light">${t('settings.light')}</button>
            <button type="button" class="${state.theme === 'dark' ? 'is-active' : ''}"
              data-action="set-theme" data-theme="dark" data-testid="theme-dark">${t('settings.dark')}</button>
          </div>
        </div>
      </div>
      <div class="setting-row">
        <div class="setting-label">
          ${t('settings.notify')}
          <div class="setting-desc">${t('settings.about')}</div>
        </div>
        <div class="setting-control">
          <button type="button" class="switch ${state.notify ? 'is-on' : ''}"
            data-action="toggle-notify" data-testid="switch-notify" aria-pressed="${state.notify}"></button>
        </div>
      </div>
      <div class="setting-row">
        <div class="setting-label">${t('settings.version')}</div>
        <div class="setting-control" data-testid="app-version">v0.1.0</div>
      </div>
    </div>`;
}

const PAGES = {
  login: { render: async () => loginHtml() },

  home: {
    async render() {
      if (has('functional-skeleton-stuck') || hasAction('skeleton-stuck', 'home')) return skeleton();
      try {
        await ensureMarkets();
      } catch (err) {
        if (has('functional-api-error-silent')) {
          markets = markets || [];
          return homeHtml();
        }
        return stateBlock(t('home.errorTitle'), t('home.errorDesc'), true);
      }
      return homeHtml();
    },
  },

  coin: {
    async render(symbol) {
      if (hasAction('skeleton-stuck', 'coin')) return skeleton();
      await ensureMarkets();
      return coinHtml(findCoin(symbol));
    },
  },

  trade: {
    async render(symbol) {
      if (hasAction('skeleton-stuck', 'trade')) return skeleton();
      await ensureMarkets();
      return tradeHtml(findCoin(symbol));
    },
  },

  kyc: { render: async () => kycHtml() },
  settings: { render: async () => settingsHtml() },
};

const NAV_OF_PAGE = {
  home: 'home', coin: 'home', trade: 'trade', kyc: 'kyc', settings: 'settings', login: '',
};

function parseRoute() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [name = 'home', param = 'BTC'] = raw.split('/');
  return { name, param: decodeURIComponent(param || 'BTC') };
}

function highlightNav(page) {
  const active = NAV_OF_PAGE[page] || '';
  document.querySelectorAll('[data-nav]').forEach((el) => {
    el.classList.toggle('is-active', el.dataset.nav === active);
  });
}

function renderLangBadge() {
  if (langBadge) langBadge.textContent = t(`lang.${LANG_KEY[getLocale()]}`);
}

function waitForImages(root, timeout = 2500) {
  const imgs = [...root.querySelectorAll('img')].filter((img) => !(img.complete && img.naturalWidth > 0));
  if (!imgs.length) return Promise.resolve();
  return Promise.race([
    Promise.all(imgs.map((img) => new Promise((resolve) => {
      img.addEventListener('load', resolve, { once: true });
      img.addEventListener('error', resolve, { once: true });
    }))),
    new Promise((resolve) => setTimeout(resolve, timeout)),
  ]);
}

async function finishRender() {
  try {
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
  } catch (err) { /* ignore */ }
  await waitForImages(appEl);
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  setReady(true);
}

async function render() {
  setReady(false);
  const { name, param } = parseRoute();
  currentPage = PAGES[name] ? name : 'home';
  highlightNav(currentPage);
  renderLangBadge();
  renderFaultBanner();

  const page = PAGES[currentPage];
  appEl.innerHTML = skeleton();

  let html;
  try {
    html = await page.render(param);
  } catch (err) {
    console.error('[mtct] render failed', err);
    html = stateBlock(t('home.errorTitle'), t('home.errorDesc'), true);
  }

  appEl.innerHTML = html;
  applyAfterRender(appEl, currentPage);

  if (has('functional-console-error') || hasAction('console-error', currentPage)) {
    setTimeout(() => {
      throw new Error('MTCT injected console error');
    }, 0);
  }

  await finishRender();
}

async function changeLocale(lang) {
  await loadLocale(lang);
  localStorage.setItem('mtct.locale', lang);
  applyI18n(document);
  renderLangBadge();
  await render();
}

async function changeTheme(theme) {
  state.theme = theme;
  localStorage.setItem('mtct.theme', theme);
  document.documentElement.dataset.theme = theme;
  await render();
}

document.addEventListener('submit', (event) => event.preventDefault());

document.addEventListener('click', async (event) => {
  const el = event.target.closest('[data-action]');
  if (!el) return;
  const action = el.dataset.action;

  switch (action) {
    case 'noop':
      return;

    case 'reload':
      location.reload();
      return;

    case 'tab':
      state.tab = el.dataset.tab;
      refreshGrid();
      return;

    case 'login': {
      const email = document.getElementById('email')?.value.trim() || '';
      const password = document.getElementById('password')?.value || '';
      const box = document.getElementById('login-message');
      if (box) {
        box.innerHTML = (!email || !password)
          ? `<div class="form-error" data-testid="form-error">${t('login.required')}</div>`
          : `<div class="form-success" data-testid="form-success">${t('login.title')}</div>`;
      }
      return;
    }

    case 'kyc-submit': {
      const name = document.getElementById('kyc-name')?.value.trim() || '';
      const docNo = document.getElementById('kyc-docno')?.value.trim() || '';
      const box = document.getElementById('kyc-message');
      if (box) {
        box.innerHTML = (!name || !docNo)
          ? `<div class="form-error" data-testid="form-error">${t('kyc.error')}</div>`
          : `<div class="form-success" data-testid="form-success">${t('kyc.success')}</div>`;
      }
      return;
    }

    case 'trade-submit':
      el.dataset.submitted = 'true';
      el.textContent = t('common.saved');
      return;

    case 'percent': {
      const amount = document.getElementById('order-amount');
      if (amount) amount.value = el.dataset.percent.replace('%', '');
      return;
    }

    case 'go-trade':
      location.hash = `#/trade/${el.dataset.symbol}`;
      return;

    case 'set-lang':
      await changeLocale(el.dataset.lang);
      return;

    case 'set-theme':
      await changeTheme(el.dataset.theme);
      return;

    case 'toggle-notify':
      state.notify = !state.notify;
      localStorage.setItem('mtct.notify', state.notify ? '1' : '0');
      el.classList.toggle('is-on', state.notify);
      el.setAttribute('aria-pressed', String(state.notify));
      return;

    default:
      return;
  }
});

document.addEventListener('input', (event) => {
  if (event.target && event.target.id === 'search') {
    state.search = event.target.value;
    refreshGrid();
  }
});

async function boot() {
  document.documentElement.dataset.theme = state.theme;
  initLocale();
  await initFaults();
  try {
    await loadLocale();
  } catch (err) {
    console.error('[mtct] locale load failed', err);
  }
  applyI18n(document);
  renderLangBadge();
  renderFaultBanner();
  window.addEventListener('hashchange', render);
  await render();
  window.__MTCT_APP__ = {
    locale: getLocale(),
    faults: activeFaults(),
    version: '0.1.0',
  };
}

boot();
