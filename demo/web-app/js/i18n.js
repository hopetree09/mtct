/**
 * i18n：语言加载与文案取值
 * 优先级：URL ?lang= > localStorage > 浏览器语言 > zh-CN
 */

export const SUPPORTED = ['zh-CN', 'en-US', 'vi-VN'];
export const LANG_KEY = { 'zh-CN': 'zh', 'en-US': 'en', 'vi-VN': 'vi' };

let dict = {};
let current = 'zh-CN';

export function getLocale() {
  return current;
}

export function initLocale() {
  const url = new URLSearchParams(location.search).get('lang');
  const saved = localStorage.getItem('mtct.locale');
  const nav = navigator.language || 'zh-CN';
  let next = url || saved || (SUPPORTED.includes(nav) ? nav : 'zh-CN');
  if (!SUPPORTED.includes(next)) next = 'zh-CN';
  current = next;
  return next;
}

export async function loadLocale(next) {
  if (next && SUPPORTED.includes(next)) current = next;
  const res = await fetch(`i18n/${current}.json`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`i18n load failed: ${current} (${res.status})`);
  dict = await res.json();
  document.documentElement.lang = current;
  return dict;
}

/** 取文案，支持 {var} 占位符；缺失时返回 key 本身，便于暴露问题 */
export function t(key, vars) {
  const value = key
    .split('.')
    .reduce((obj, part) => (obj && typeof obj === 'object' && part in obj ? obj[part] : undefined), dict);
  if (typeof value !== 'string') return key;
  if (!vars) return value;
  return Object.entries(vars).reduce(
    (out, [name, val]) => out.split(`{${name}}`).join(String(val)),
    value
  );
}

/** 翻译静态标记（data-i18n） */
export function applyI18n(root = document) {
  root.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
}
