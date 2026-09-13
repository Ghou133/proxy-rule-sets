# Source audit

Snapshot: `0fa1f5fa40ad4233f934e2a22ff14346b6083051b2ab0fa8531f5b172421c831`. Full source read as UTF-8.

87 lines; 7 blank; 43 comments; 22 active rule declarations; 14 non-rule configuration lines.

Sections: [custom] (line 1).

| Rule type | Count |
|---|---:|
| DOMAIN | 0 |
| DOMAIN-SUFFIX | 0 |
| DOMAIN-KEYWORD | 0 |
| IP-CIDR | 0 |
| IP-CIDR6 | 0 |
| IP-ASN | 0 |
| GEOIP | 1 |
| USER-AGENT | 0 |
| URL-REGEX | 0 |
| PROCESS-NAME | 0 |
| PROCESS-PATH | 0 |
| DEST-PORT | 0 |
| DST-PORT | 0 |
| SRC-IP-CIDR | 0 |
| AND | 0 |
| OR | 0 |
| NOT | 0 |
| RULE-SET | 20 |
| FINAL | 1 |
| MATCH | 0 |

| Policy | Count |
|---|---:|
| Proxies | 3 |
| DIRECT | 15 |
| DMM | 1 |
| Japan | 1 |
| Hongkong | 1 |
| Others | 1 |

Exact duplicates: 0; same matcher / multiple policies: 0. INFORMATIONAL_ONLY. No semantic redundancy analysis or removal.

Policyless: 0; invalid: 0; unsupported: 1; ambiguous: 0; no-resolve: 0.

PRESERVE SOURCE ORDER. Per-policy projection preserves every occurrence and relative order. It cannot in general preserve interleaved cross-policy priority; canonical/ordered.json is authoritative for global order. External contents are unknown, and overlaps inside them have NOT been audited.

Comment text is preserved only in the frozen source; generated comments describe provenance and terminal handling. No matcher domain/IP rewrites are performed. Known proxy-group/generator settings are recorded as non-rule configuration, not emitted.

SOURCE_ACCOUNTING: 22 = 1 + 1 + 0 + 20 + 0 (generated + unsupported + ambiguous + external_dependency + invalid_with_evidence).

## Expanded scope

Later user instruction explicitly authorized materializing the nine Ghou133-owned references. See [owned_source_audit.md](owned_source_audit.md) and expanded_source_accounting.json. Third-party content was fetched only transiently to compare YAML candidates; it was not copied into generated datasets. Original 4.ini counts above remain unchanged.
