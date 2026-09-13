# Rule Sets

你的历史规则规范化仓库：保留重复、匹配范围、原策略与源顺序。仅提供规则数据和引用片段，不包含节点、订阅、代理组、DNS 或完整主配置。

## Upstream

[https://raw.githubusercontent.com/Ghou133/Ghou133.github.io/refs/heads/master/archives/4.ini](https://raw.githubusercontent.com/Ghou133/Ghou133.github.io/refs/heads/master/archives/4.ini)

Commit: `a29c67805b1dd7721fe896d0a64eb93ba7e29813`

SHA-256: `0fa1f5fa40ad4233f934e2a22ff14346b6083051b2ab0fa8531f5b172421c831`

`4.ini` 有 22 个规则声明：9 个你仓库内的引用已冻结、完整审计并转换；11 个第三方引用直接使用其远程文件；另有 GEOIP 和 FINAL。各冻结文件的 commit、SHA-256、下载时间见 upstream/*metadata.json。原始 4.ini 永不覆盖。

## Generated Files

| File | Format | Rules | Purpose |
|---|---|---:|---|
| [canonical/proxies.list](canonical/proxies.list) | typed list | 35 | Policy projection; do not use to reorder global calls |
| [mihomo/proxies.yaml](mihomo/proxies.yaml) | YAML | 35 | Policy projection |
| [shadowrocket/proxies.list](shadowrocket/proxies.list) | typed list | 35 | Policy projection |
| [canonical/direct.list](canonical/direct.list) | typed list | 131 | Policy projection; do not use to reorder global calls |
| [mihomo/direct.yaml](mihomo/direct.yaml) | YAML | 131 | Policy projection |
| [shadowrocket/direct.list](shadowrocket/direct.list) | typed list | 123 | Policy projection |
| [canonical/japan.list](canonical/japan.list) | typed list | 110 | Policy projection; do not use to reorder global calls |
| [mihomo/japan.yaml](mihomo/japan.yaml) | YAML | 110 | Policy projection |
| [shadowrocket/japan.list](shadowrocket/japan.list) | typed list | 110 | Policy projection |
| [canonical/hongkong.list](canonical/hongkong.list) | typed list | 5 | Policy projection; do not use to reorder global calls |
| [mihomo/hongkong.yaml](mihomo/hongkong.yaml) | YAML | 5 | Policy projection |
| [shadowrocket/hongkong.list](shadowrocket/hongkong.list) | typed list | 5 | Policy projection |


`canonical/ordered.json` 是内部唯一真源，记录每条本地规则的行号、原策略，以及第三方引用的全局顺序。`.list`、客户端文件均是投影，不手工编辑。`mihomo/segments/` 与 `shadowrocket/segments/` 按源位置分段，供下面的保序示例使用；完整计数见 [generated_counts.json](artifacts/generated_counts.json)。

## Mihomo Usage

直接使用 [完整保序 rule-providers / rules 片段](examples/mihomo-rules.yaml)。其中第三方地址已核对；本地地址在发布前为 `<GITHUB_RAW_BASE>`。发布后执行 `python scripts/update_rules.py --offline --raw-base https://raw.githubusercontent.com/OWNER/REPO/main` 填入真实地址。

只想加载某个自有文件时可参考：

```yaml
rule-providers:
  own-boost:
    type: http
    behavior: classical
    format: yaml
    url: <GITHUB_RAW_BASE>/mihomo/segments/005-boost.yaml
    path: ./ruleset/own-boost.yaml
    interval: 86400
rules:
  - RULE-SET,own-boost,<YOUR_POLICY_FOR_Proxies>
```

`<YOUR_POLICY_FOR_...>` 必须替换为你已有策略名；没有创建任何代理组。`Proxies`、`DMM`、`Japan`、`Hongkong`、`Others` 保留为独立策略，不擅自合并成 PROXY。完整示例最后将原 FINAL 表达为父级 MATCH。

## Shadowrocket Usage

[完整保序片段](examples/shadowrocket-rules.list)使用原第三方文本与自有 typed RULE-SET 文件。例如：

```text
RULE-SET,<GITHUB_RAW_BASE>/shadowrocket/segments/005-boost.list,<YOUR_POLICY_FOR_Proxies>
```

不是 DOMAIN-SET。自有 Windows PROCESS-NAME 共 8 条保留在 unsupported/shadowrocket.list；未做 iOS 实机验证。

## Statistics

本地有效叶子规则 282；生成 281；unsupported 1；ambiguous 0；invalid 0。第三方依赖 11。扩展账本：**293 = 281 + 1 + 0 + 11 + 0**（generated + unsupported + ambiguous + external_dependency + invalid_with_evidence）。原模板 22 个声明另有独立账本，容器引用与叶子规则不重复相加。

Exact duplicates 17，全部保留、删除 0；semantic dedup 禁用；同 matcher 多 policy 1，仅观察、全部保留。完整位置见 [dedup_report.json](artifacts/dedup_report.json) / [conflicts.json](artifacts/conflicts.json)。

## Order and compatibility

**PRESERVE SOURCE ORDER / NO ORDER LOSS / NO SILENT DROP。** 不排序、不去重、不改 domain/IP matcher，不把 IP 样式的 DOMAIN-SUFFIX 改成 IP-CIDR。仅去除字段边界空格、统一类型和分隔格式，移除策略字段及 [] 包装。no-resolve 保留；Windows 进程名内部空格保留。生成文件 UTF-8、LF、无 BOM，冻结文件保留原字节。

实际使用应采用 segments 保序片段。将全部 DIRECT 合为一次调用会改变与其他策略的交错优先级，所以策略聚合文件不能直接替代原全局顺序。

**客户端存在无法等价表达的规则。** 原第三方 Download 含 7 条 URL-REGEX，Microsoft 含 3 条 USER-AGENT；Mihomo 不支持，加载原文本会警告并跳过这 10 条。保留原引用和完整不支持行证据，不伪装为无损转换。自有 Windows 进程规则仅给 Mihomo 生成。详细选择及限制见 [兼容报告](artifacts/compatibility_report.md)。同名但内容不同的第三方 YAML 未替换；不是为了“用 YAML”而删规则。

## Update

```sh
python -m pip install -r requirements.txt
python scripts/update_rules.py
python -m unittest discover -s tests -v
```

在线更新固定上游 commit，重新抓取自有文件，并核对第三方 YAML 与原文本。仅比较，不将第三方整库写进仓库。`--offline` 使用本地快照和核对记录，完全离线可复现；`--audit-only` 只生成 4.ini 审计。相同输入不会刷新时间戳，重复运行字节一致。初始快照冻结，后续变化保存在内容寻址目录。未审阅的新类型隔离并记账。

GitHub Actions 提供测试及每周更新 PR，不自动合并；需在仓库设置允许 Actions 创建 PR。上游未知语法、许可证变化和报告中的兼容缺口需要在合并前审阅。

## Attribution

来源为 Ghou133/Ghou133.github.io；第三方分别为 ACL4SSR/ACL4SSR 与 blackmatrix7/ios_rule_script。所有 attribution 与许可范围见 [UPSTREAM.md](UPSTREAM.md)。上游完整树未发现 LICENSE/LICENCE/COPYING；不为规则数据擅自声明 MIT。第三方原文件只远程引用，不复制整份内容。原配置中的装饰、教程和代理组只保留于冻结证据。
