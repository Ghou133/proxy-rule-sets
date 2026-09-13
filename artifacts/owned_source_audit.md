# Owned source audit

All nine owned files were read in full before conversion. Policy inherited exclusively from their active 4.ini reference.

| File | Rules | Policy | Source line |
|---|---:|---|---:|
| boost.list | 8 | Proxies | 5 |
| DownloadPatch.list | 63 | DIRECT | 23 |
| steamdownload.list | 49 | DIRECT | 26 |
| gameplatform.list | 27 | Proxies | 32 |
| DmmDLFz.list | 110 | Japan | 38 |
| notJP.list | 5 | Hongkong | 41 |
| windowsoft.list | 7 | DIRECT | 52 |
| kaspersky.list | 2 | DIRECT | 53 |
| UnBanPatch.list | 9 | DIRECT | 54 |

Rule types: {"DOMAIN-SUFFIX": 159, "DOMAIN-KEYWORD": 11, "PROCESS-NAME": 8, "IP-CIDR": 69, "DOMAIN": 33, "GEOIP": 1, "FINAL": 1}.

Policies (local leaf occurrences): {"Proxies": 35, "DIRECT": 131, "Japan": 110, "Hongkong": 5, "Others": 1}.

Exact duplicate occurrences 17; same matcher multiple policies 1. All retained; no semantic coverage analysis. See dedup_report.json and conflicts.json for every source location. No matcher rewrite; dotted numeric DOMAIN-SUFFIX values retain their original type. Windows process names retain internal spaces.

Expanded SOURCE_ACCOUNTING: 293 = 281 + 1 + 0 + 11 + 0.
