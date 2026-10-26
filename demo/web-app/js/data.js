/**
 * 数据层：所有数据都走 fetch 拉本地 JSON
 * 弱网测试需要 page.route 对数据请求注入延迟/失败，内联数据会测不到东西。
 */

export async function fetchMarkets() {
  const res = await fetch('data/markets.json', { cache: 'no-store' });
  if (!res.ok) throw new Error(`markets HTTP ${res.status}`);
  return res.json();
}
