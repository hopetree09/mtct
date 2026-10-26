# DemoX Exchange · 演示站（被测对象）

这是 MTCT 兼容性测试系统的**靶子**：一个自研的、轻量的、可注入缺陷的交易所网页应用。
它不是产品，是"被测对象 + 缺陷基准集发生器"。

## 运行

```powershell
# 在仓库根目录
python -m http.server 8765 --directory demo/web-app

# 浏览器打开
http://127.0.0.1:8765/
```

无构建步骤、无 npm 依赖、无后端：纯 HTML + CSS + 原生 JS + JSON 假数据。

## 页面

| 路由 | 页面 | 主要测试点 |
|---|---|---|
| `#/home` | 行情列表 | 卡片布局、数字格式、搜索、Tab、骨架屏、弱网 |
| `#/coin/BTC` | 币种详情 | 价格排版、统计格、走势图、按钮长文案 |
| `#/trade/BTC` | 交易下单 | 盘口列表、下单面板、两栏布局、窄视口 |
| `#/kyc` | 身份认证 | 表单校验、长地址、错误提示布局 |
| `#/login` | 登录 | 表单校验、按钮可用性 |
| `#/settings` | 设置 | 三语切换、深浅主题、开关控件 |

## URL 参数

| 参数 | 说明 | 示例 |
|---|---|---|
| `lang` | 强制语言：`zh-CN` / `en-US` / `vi-VN` | `?lang=vi-VN` |
| `fault` | 故障注入，逗号分隔多个 id | `?fault=layout-card-overflow,vi-clip-price` |
| `debug` | `1` 时左下角显示当前激活的故障 | `?debug=1` |

注意：hash 路由下参数要写在 `#` 之前，例如
`http://127.0.0.1:8765/?lang=vi-VN&fault=layout-card-overflow#/home`

## 可测性钩子（给测试系统用）

| 钩子 | 说明 |
|---|---|
| `window.__MTCT_READY__` | 布尔值，页面渲染 + 字体 + 图片全部就绪后为 true |
| `<html data-mtct-ready="1">` | 同一状态的 DOM 信号，方便 CSS/断言使用 |
| `window.__MTCT_APP__` | `{ locale, faults, version }` 运行态快照 |
| `window.__MTCT_FAULT_MANIFEST__` | 全部故障清单（含类别/严重度/期望检出方式） |
| `window.__MTCT_FAULT_IDS__` | 本次生效的故障 id |
| `data-testid` | 关键元素统一带 testid，供定位器回退链第一级使用 |

## 故障清单（22 条）

| id | 页面 | 类别 | 期望检出方式 |
|---|---|---|---|
| layout-card-overflow | home | 布局溢出 | 布局不变量 |
| layout-btn-overlap | trade | 布局重叠 | 布局不变量 |
| layout-label-overlap | kyc | 布局重叠 | 布局不变量 |
| i18n-btn-truncate | coin | 国际化截断 | 布局不变量 |
| i18n-pair-truncate | home | 国际化截断 | 布局不变量 |
| i18n-address-truncate | kyc | 国际化截断 | 布局不变量 |
| vi-clip-price | home | 变音符号裁切 | 视觉 / 字体度量 |
| vi-clip-stat | coin | 变音符号裁切 | 视觉 / 字体度量 |
| vi-clip-btn | trade | 变音符号裁切 | 视觉 |
| zoom-trade-nostack | trade | 缩放错位 | 布局不变量 |
| zoom-grid-fixed | home | 缩放错位 | 布局不变量 |
| zoom-login-fixed | login | 缩放错位 | 布局不变量 |
| contrast-change | home | 对比度 | 规则（WCAG） |
| contrast-label | kyc | 对比度 | 规则（WCAG） |
| contrast-nav | all | 对比度 | 规则（WCAG） |
| font-mono-price | coin | 字体度量 | 视觉 |
| font-tab-big | home | 字体度量 | 布局不变量 |
| font-small-label | settings | 字体度量 | 视觉 |
| functional-api-error-silent | home | 错误态缺失 | 功能断言 |
| functional-skeleton-stuck | home | 加载态卡死 | 视觉 / 就绪门控 |
| functional-btn-disabled | login | 功能破坏 | 功能断言 |
| functional-console-error | all | 控制台异常 | 功能断言 |

## 为什么不用真实网站当靶子

1. 无法注入确定性缺陷，就没有 ground truth，误报率/召回率算不出来；
2. 无法加 `data-testid`、就绪钩子，定位器和弱网截图都不稳定；
3. 真实站点随时改版，测试结果不可复现；
4. 拿公司产品或第三方站点做自动化测试有合规风险。

## 已知限制

- 只覆盖浏览器形态（桌面 Web），不做原生客户端；
- 视觉"缩放"用窄 CSS 视口模拟（150% 缩放 ≈ 视口缩到 2/3），不是系统级 DPI 切换；
- 字体使用系统字体，跨机器渲染可能有细微差异，正式做基线时需固定环境；
- 走势图用确定性 SVG 生成，不是真实 canvas 图表（避免截图抖动）。

## 下一步

- 把 22 条故障扩到 7 类 × 约 17 个变体 = 120 例（按"故障族 × 页面元素"组合生成）；
- 给每条故障补 `expected_detector` 与标签 JSON，交给评测脚本读取；
- 用 Playwright 写第一条端到端用例：`?fault=layout-card-overflow` 下断言"无横向滚动"失败。
