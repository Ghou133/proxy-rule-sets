# Locally maintained third-party rules

| Source | Canonical | Mihomo | Shadowrocket | License |
|---|---:|---:|---:|---|
| ACL4SSR/ACL4SSR/unban | 31 | 31 | 31 | CC-BY-SA-4.0 |
| ACL4SSR/ACL4SSR/download | 22 | 15 | 2 | CC-BY-SA-4.0 |
| blackmatrix7/ios_rule_script/microsoft | 673 | 670 | 668 | GPL-2.0 |
| ACL4SSR/ACL4SSR/googlecn | 29 | 29 | 29 | CC-BY-SA-4.0 |
| ACL4SSR/ACL4SSR/proxygfwlist | 6986 | 6986 | 6986 | CC-BY-SA-4.0 |

Every output file includes original repository/file URLs, pinned commit, license and modification date. All original occurrences remain in canonical/vendor, frozen source and per-source ledgers. Unsupported rules remain in unsupported/vendor. No sorting, deduplication, matcher changes or inferred policies. Separate license namespaces are retained; these copies are not merged into the unlicensed own-policy files.

Default updates rebuild these files from their frozen snapshots. To intentionally synchronize from original upstream, run `python scripts/update_rules.py --refresh-vendored`; this stores new immutable snapshots and regenerates reports. Normal runtime loads this repository's Raw files. Six equivalent third-party YAML references remain remote.

Mihomo cannot implement 7 URL-REGEX and 3 USER-AGENT entries. These are retained, not approximated. Shadowrocket exports conservative verified syntax only: Windows process rules and the 10 unverified regex/agent rules remain in its unsupported ledger. No iOS runtime equivalence is claimed.
