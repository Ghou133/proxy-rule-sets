# Clash Verge Rev 全局扩展脚本

这里使用 JavaScript 全局扩展脚本，入口为 `main(config)`。脚本根据实际订阅节点构建组并追加规则，比静态 YAML 覆写适合两个版本共用。

- [有落地版](with-landing.js)：AI 默认经过“中转节点 → 落地出口”。中转优先现有日本节点，再回退其他地区；不会自动将 AI 切回机场出口。公开版本需在顶部指定已存在的 `landingNodeName`，或仅在本机设置 `landingProxy`。不要把私有连接参数提交到公开仓库。
- [无落地版](without-landing.js)：AI 默认使用“机场出口”，不创建落地节点或中转链路。可在唯一的“AI”策略组中统一选择日本、新加坡、美国或机场节点。

两版都只有一个 **AI** 组。订阅中的同名 AI/ChatGPT/OpenAI/Claude/Gemini 组和其引用统一为 AI。规则顺序为：3 个 AI provider 调用 → 本仓库原始顺序的规则调用 → 订阅原规则。保留订阅终止规则；没有时补充“其他流量”。旧规则中的 DIRECT/其他明确策略不改成 AI，只有新增 AI 匹配规则优先；这是本扩展明确新增的功能。

AI 规则来自 [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat/tree/meta/geo/geosite)，使用 `openai`、`anthropic`、`google-gemini` 的 YAML domain provider。核对时分别为 22、8、41 条；客户端每 24 小时刷新远程规则。来源/commit/校验值见 [ai_sources.json](ai_sources.json)。不复制或篡改上游内容；规则也可能包含其相关产品，如 Sora、NotebookLM。

## 使用

Clash Verge Rev → 订阅 → 全局扩展脚本 → 编辑文件，将相应版本内容替换进去并保存，然后重新应用当前订阅。两版二选一，不串联两个脚本。不要放到“全局扩展配置”的 YAML 编辑器中。

“地区·日本/香港”等组没有匹配节点时为 REJECT，不擅自换成其他地区。节点只有 proxy-providers 时无法在脚本阶段得知远端节点列表，中转使用提供者节点池，不承诺日本优先；地区组可手动选择过滤后的提供者节点。已有 dialer-proxy 的内联节点/提供者不参加中转池，避免链路环。

`transitHealthUrl` 可设置只用于测试前置节点到落地机器的可达性；为空时使用一般连通性探测，不等于落地服务可用。AI 网站账号、区域解锁与落地密码可用性需要实际网络验证。

脚本不会修改 DNS、TUN、节点订阅 URL、监听端口或系统代理设置。原文件先备份，再切换脚本。

## 维护

`python scripts/build_extensions.py` 从现有保序片段重新生成两个独立脚本。`node --test tests/extensions.test.cjs` 验证行为。公开文件不读取本机私有文件、不联网执行 JavaScript，也不含落地密码。

依据：[Clash Verge Rev 扩展机制](https://www.clashverge.dev/guide/extend.html)、[Mihomo dialer-proxy](https://wiki.metacubex.one/config/proxies/dialer-proxy/)。扩展在原规则数据工程之外独立存放，便于不使用扩展的用户继续只订阅规则。
