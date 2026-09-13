# Rule Sets

保留原策略、原顺序、重复项的规则数据仓库。只提供规则与引用片段，不包含节点、订阅、代理组、DNS 或完整主配置。

## Upstream

来源：[Ghou133/4.ini](https://raw.githubusercontent.com/Ghou133/Ghou133.github.io/refs/heads/master/archives/4.ini)。原始 commit、SHA-256、下载时间见 [metadata](upstream/metadata.json)；9 个自有引用共 280 条规则均已冻结并转换。

5 个第三方原文本与同名 YAML 不一致，因此本仓库维护其完整规范版本；6 个核对一致的第三方 YAML 继续远程引用。每个本地第三方文件都注明原仓库和许可证。默认使用冻结版本，需要同步时显式更新。

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
| [mihomo/vendor/acl4ssr/unban.yaml](mihomo/vendor/acl4ssr/unban.yaml) | YAML | 31 | Local maintained copy; CC-BY-SA-4.0 |
| [shadowrocket/vendor/acl4ssr/unban.list](shadowrocket/vendor/acl4ssr/unban.list) | typed list | 31 | Local maintained copy; CC-BY-SA-4.0 |
| [mihomo/vendor/acl4ssr/download.yaml](mihomo/vendor/acl4ssr/download.yaml) | YAML | 15 | Local maintained copy; CC-BY-SA-4.0 |
| [shadowrocket/vendor/acl4ssr/download.list](shadowrocket/vendor/acl4ssr/download.list) | typed list | 2 | Local maintained copy; CC-BY-SA-4.0 |
| [mihomo/vendor/blackmatrix7/microsoft.yaml](mihomo/vendor/blackmatrix7/microsoft.yaml) | YAML | 670 | Local maintained copy; GPL-2.0 |
| [shadowrocket/vendor/blackmatrix7/microsoft.list](shadowrocket/vendor/blackmatrix7/microsoft.list) | typed list | 668 | Local maintained copy; GPL-2.0 |
| [mihomo/vendor/acl4ssr/googlecn.yaml](mihomo/vendor/acl4ssr/googlecn.yaml) | YAML | 29 | Local maintained copy; CC-BY-SA-4.0 |
| [shadowrocket/vendor/acl4ssr/googlecn.list](shadowrocket/vendor/acl4ssr/googlecn.list) | typed list | 29 | Local maintained copy; CC-BY-SA-4.0 |
| [mihomo/vendor/acl4ssr/proxygfwlist.yaml](mihomo/vendor/acl4ssr/proxygfwlist.yaml) | YAML | 6986 | Local maintained copy; CC-BY-SA-4.0 |
| [shadowrocket/vendor/acl4ssr/proxygfwlist.list](shadowrocket/vendor/acl4ssr/proxygfwlist.list) | typed list | 6986 | Local maintained copy; CC-BY-SA-4.0 |


`canonical/ordered.json` 记录全局调用顺序与每个来源的 canonical 文件。自有策略文件与第三方许可目录保持分离；引用示例按源位置调用，不能把所有 DIRECT 聚合提前。segments 与聚合文件是相同数据的不同投影，统计不重复相加。

## Mihomo Usage

[完整保序片段](examples/mihomo-rules.yaml)包含 rule-providers 和 rules，所有本地文件都使用本仓库地址。发布前 `<GITHUB_RAW_BASE>` 是待替换占位符；发布脚本会填入实际地址。

```yaml
rule-providers:
  legacy-download:
    type: http
    behavior: classical
    format: yaml
    url: <GITHUB_RAW_BASE>/mihomo/vendor/acl4ssr/download.yaml
    path: ./ruleset/legacy-download.yaml
    interval: 86400
rules:
  - RULE-SET,legacy-download,DIRECT
```

该文件保留 13 条进程规则及 2 条域名规则，不采用只有 2 条的第三方同名 YAML。7 条 URL-REGEX 在 unsupported/vendor 中保留；Mihomo 本身不支持，不能通过另建文件解决。完整示例的 `<YOUR_POLICY_FOR_...>` 替换为你现有策略，未创建任何代理组。

## Shadowrocket Usage

```text
RULE-SET,<GITHUB_RAW_BASE>/shadowrocket/vendor/acl4ssr/unban.list,DIRECT
```

[完整保序片段](examples/shadowrocket-rules.list)。保留类型，不是 DOMAIN-SET。Windows 进程规则及未验证的 URL-REGEX/USER-AGENT 规则单独留存；没有 iOS 实机验证。

## Statistics

完整有效账本：**8029 = 8012 + 11 + 0 + 6 + 0**（generated + unsupported + ambiguous + external_dependency + invalid_with_evidence）。Mihomo 本地生成 8012 条；Shadowrocket 本地生成 7989 条。Unexplained loss = 0。

有效数据流 exact duplicate occurrences 130，全部保留，删除 0；同 matcher 多 policy 35，仅观察、不消解。语义去重禁用。见 [总账本](artifacts/effective_source_accounting.json)、[重复报告](artifacts/effective_duplicates.json)、[多策略报告](artifacts/effective_conflicts.json)。

## Update

```sh
python -m pip install -r requirements.txt
python scripts/update_rules.py
python -m unittest discover -s tests -v
```

通常更新自有上游并从冻结第三方快照重建。需要主动同步本地维护的第三方文件时：`python scripts/update_rules.py --refresh-vendored`。离线复现：`python scripts/update_rules.py --offline`。原始快照永不覆盖；相同输入重复运行不产生 Git 差异。GitHub Actions 检查并提出每周更新 PR，不自动合并。

仅做类型、字段边界空格、UTF-8/LF 格式转换；不改 matcher、no-resolve、进程名内部空格，不排序、不删重复。未知语法保留并记账。完整兼容范围见 [兼容报告](artifacts/compatibility_report.md)。

## Attribution

自有来源 Ghou133/Ghou133.github.io 未声明许可证，不擅自赋予 MIT。ACL4SSR 副本及格式转换保留 CC BY-SA 4.0；blackmatrix7 副本及格式转换保留 GPLv2，分别放在独立目录。完整许可证、原始文本、来源与修改说明随仓库提供，见 [UPSTREAM.md](UPSTREAM.md)。这些第三方数据不是本仓库原创。
