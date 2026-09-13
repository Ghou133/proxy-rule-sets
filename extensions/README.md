# Global Extension

两版使用 Clash Verge Rev 全局扩展脚本，完全替换订阅的 rules、proxy-groups、rule-providers，保留订阅节点及 DNS、TUN、端口等其他设置。不要粘进 YAML 编辑器。

| Version | Visible groups | AI default |
|---|---|---|
| [With landing](with-landing.js) | AI / Proxy / Relay | Exit |
| [Without landing](without-landing.js) | AI / Proxy | Proxy |

AI 统一处理 ChatGPT、Claude、Gemini。有落地版为手动 select 组，第一项 Exit，失败不会自动切换 Proxy；仅手选 Proxy 才绕过落地。Exit 通过 Relay 连接。Relay 默认 Latency 自动测速，所有地区平等参与，也可手选节点，没有日本优先。

Auto、Latency、Japan、Hongkong、DMM 为隐藏内部组。隐藏需要客户端界面支持。后三组保留历史规则的明确地域策略，不限制 Relay。规则顺序为三个 AI provider、本仓库保序片段、MATCH,Proxy；订阅原规则移除。

AI YAML 来源：[MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat/tree/meta/geo/geosite)，openai、anthropic、google-gemini 核对时分别 22、8、41 条，每天刷新。来源记录见 ai_sources.json。远程规则覆盖决定哪些请求归 AI，未来新增域名不保证提前收录。

## Use

二选一手动放入全局扩展脚本。本次不自动替换、不重载。公开有落地模板需设置 landingNodeName 或本机 landingProxy；私人连接版仅在本机交付，不上传 GitHub。

首次应用确认规则模式及 AI → Exit；客户端可能记住以前手选的 AI 出口，脚本不会清除选择缓存。自动选择 Relay 不会绕过 Exit。transitHealthUrl 仅测试中转连通性，不等于落地认证成功。已有 dialer-proxy 的节点不进入自动池。提供者节点的测速由 proxy-provider 自身健康检查负责。

## Validation

python scripts/build_extensions.py 生成两版。node --test tests/extensions.test.cjs 验证完全接管、英文命名、手动 AI 选择、全地区中转、无环引用和幂等性。两版通过本机 Mihomo v1.19.29 隔离配置校验；未对当前连接注入故障。

依据：[扩展机制](https://www.clashverge.dev/guide/extend.html)、[dialer-proxy](https://wiki.metacubex.one/config/proxies/dialer-proxy/)、[代理组及 hidden](https://wiki.metacubex.one/config/proxy-groups/)。
