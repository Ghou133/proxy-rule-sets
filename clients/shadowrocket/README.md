# Shadowrocket

| File | Groups | AI default |
|---|---|---|
| [with-landing.conf](with-landing.conf) | Proxy / AI / Relay | Exit |
| [without-landing.conf](without-landing.conf) | Proxy / AI | Proxy |

Proxy 排最上面，默认 Auto，有落地版可手选 Exit。Relay 提供 Auto、Latency 和 Nodes，不按国家筛选。Auto 测试普通联网，Latency 测试指定落地健康地址；Nodes 提供全部订阅节点供手选。三个辅助组设置隐藏，没有影音、游戏等额外规则组。

AI 始终是手动选择组：Exit 失败不会自动切换 Proxy；仅手选 Proxy 才绕过落地。保持原配置的 DNS、IPv6、QUIC 等设置；REJECT 仅用于不支持的 UDP 行为，不加载广告拦截规则。

## Import

公开文件为模板：将 SUBSCRIPTION 替换为手机中订阅的准确名称（注意大小写）。有落地模板中的地址、密码也需本机填写。已配置的私人版本只在本机交付，不能用公开 Raw 文件覆盖私人版本。

有落地版导入后，先在手机上将 **Exit 节点 → 代理通过 → Relay**，再使用配置，并确认 **AI → Exit**。配置文件没有注入未经验证的 chain/underlying-proxy 字段；纯文本导入不能在本项目中保证自动完成这一步。`close-if-proxy-chain-missing=true` 保留，用于已建立代理链的中转关联丢失时关闭连接，不能代替初次绑定。

全局路由选择“配置”，并关闭手机端另外设置的自动回退。本文文件不会自动安装或修改当前生效配置。当前环境不能操作 iOS，尚未完成手机端导入与断链实测。

## Remote rules

按 AI → LAN → China → ChinaDomain → GEOIP CN → FINAL 的顺序。国内与 LAN 使用 DIRECT，不增加直连选择组。AI 的匹配优先级保持高于国内规则。

- [iab0x00/ProxyRules](https://github.com/iab0x00/ProxyRules)：沿用用户指定 AI 源，核对为 49 条，包含 ChatGPT、Claude、Gemini，以及 Copilot/Grok 等。
- [blackmatrix7 China](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Shadowrocket/China)：China.list 是 RULE-SET（63 条），China_Domain.list 是 DOMAIN-SET（3,689 条），按维护者说明配套使用。
- [blackmatrix7 LAN](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Shadowrocket/Lan)：140 条 RULE-SET。

已修复粘贴内容的 Markdown 链接包裹、转义星号和参数空格；将 Quantumult X 国内文件换为上述 Shadowrocket 原生两份文件。去掉 AdvertisingLite；不展开、复制或去重第三方远程规则。源 commit、SHA-256、数量见 [sources.json](sources.json)。远程文件可能更新，实际加载范围以客户端更新后的内容为准。

## Update

```sh
python scripts/build_extensions.py
python scripts/check_shadowrocket_sources.py
python -m unittest discover -s tests -v
```

生成器为 scripts/build_shadowrocket.py；支持通过 `--private-options` 与仓库外 `--output` 在本机生成私人文件。每周仓库更新工作流会复查远程源；手机通过“配置 → 更新/编译配置”刷新远程规则。

参考：[Shadowrocket 社区维护手册](https://github.com/LOWERTOP/Shadowrocket#代理通过代理链)。来源规则不声明为本项目原创；本目录仅引用其 URL，不重新分发规则内容。
