# Global Extension

两版使用 Clash Verge Rev 全局扩展脚本，完全替换订阅的 rules、proxy-groups、rule-providers，保留订阅节点及 DNS、TUN、端口等其他设置。不要粘进 YAML 编辑器。

| Version | Visible groups | AI default |
|---|---|---|
| [With landing](with-landing.js) | Proxy / AI / DMM / Relay | Exit |
| [Without landing](without-landing.js) | Proxy / AI / DMM | Auto（可直接选全部节点） |

AI 统一处理 ChatGPT、Claude、Gemini。有落地版为手动 select 组，第一项 Exit，失败不会自动切换 Proxy；仅手选 Proxy 才绕过落地。Exit 通过 Relay 连接。

Proxy 始终位于第一组，默认 Auto，有落地版也可手选 Exit。Relay 只列首选地区：JP、HK、SG、TW、US、Other；内联订阅只显示实际存在的地区。每个选项优先尝试本地区节点，全部被健康检查判定不可用时自动尝试其他地区，恢复后重新优先本地区。默认是第一个存在的地区，可手动更改。无具体节点或 Latency 选项；不会引用 Proxy 或 Exit，因此 Proxy 选择 Exit 时也不会形成环。

地区内及备用节点按订阅相对顺序尝试，不寻找所谓“最低延迟”。健康检查计划每 60 秒运行，使用 transitHealthUrl（未设置则使用 healthUrl）；检查失败不等于任意应用故障，结果也不代表完整落地链路性能。切换需要检测时间，不保证已有连接无缝迁移。提供者节点依赖其可用性信息及内核探测。

Relay 显示的是首选地区；自动回退后它仍可能显示 JP，而实际中转已在其他地区。可查看连接链或对应回退组的当前节点确认。

Auto、地区首选回退组、Japan、Hongkong 为隐藏内部组。隐藏需要客户端界面支持。Japan/Hongkong/DMM 保留历史规则的明确地域策略，与 Relay 的 JP/HK 等首选项独立；没有因此改变历史规则的地域策略。规则顺序为三个 AI provider、本仓库保序片段、MATCH,Proxy；订阅原规则移除。

AI YAML 来源：[MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat/tree/meta/geo/geosite)，openai、anthropic、google-gemini 核对时分别 22、8、41 条，每天刷新。来源记录见 ai_sources.json。远程规则覆盖决定哪些请求归 AI，未来新增域名不保证提前收录。

## Use

二选一手动放入全局扩展脚本。本次不自动替换、不重载。公开有落地模板需设置 landingNodeName 或本机 landingProxy；私人连接版仅在本机交付，不上传 GitHub。

首次应用确认规则模式及 AI → Exit；客户端可能记住以前手选的 AI 出口，脚本不会清除选择缓存。自动选择 Relay 不会绕过 Exit。transitHealthUrl 仅测试中转连通性，不等于落地认证成功。已有 dialer-proxy 的节点不进入自动池。提供者节点的测速由 proxy-provider 自身健康检查负责。

## Validation

python scripts/build_extensions.py 生成四版（含多订阅两版）。node --test tests/extensions.test.cjs 验证完全接管、地区优先、手动 AI 选择、无环引用和幂等性。两版通过本机 Mihomo v1.19.29 隔离配置校验；未对当前连接注入故障。

`python scripts/verify_relay_failover.py --core <mihomo路径> --output <报告路径>` 使用本地模拟节点和单独内核，验证同地区/跨地区故障、恢复、Exit 失败及手动绕过，覆盖内联节点和多个 proxy-provider。测试主动触发检查，不用于测量定时切换的真实耗时。结果见 artifacts/relay_failover_verification.json。

依据：[扩展机制](https://www.clashverge.dev/guide/extend.html)、[dialer-proxy](https://wiki.metacubex.one/config/proxies/dialer-proxy/)、[代理组及 hidden](https://wiki.metacubex.one/config/proxy-groups/)。

手机端配置见 [Shadowrocket](../clients/shadowrocket/README.md)，分别提供有落地/无落地版本。按用户最终选择，本项目本轮不交付 Android 适配。

PC 多订阅另提供 [无落地](multi-subscription.js) / [有落地](multi-subscription-with-landing.js)，使用同一份 [本地入口模板与说明](MULTI_SUBSCRIPTION.md)。所有 PC 无落地版 AI 都可直接选择全部可用节点，不必进入 Proxy。

DMM 为可见手动选择组：Japan 自动选择项 + 全部日本节点（包括远程 provider）。地区由节点名称筛选，实际是否支持 DMM 需自行确认。

有落地两版的 DMM 额外提供 Exit 手动选项，仍默认 Japan；无落地版没有 Exit。
