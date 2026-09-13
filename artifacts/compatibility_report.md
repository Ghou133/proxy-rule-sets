# Compatibility and third-party YAML audit

Own-source PROCESS-NAME is emitted for Mihomo only. Eight Windows process rules cannot be represented reliably by Shadowrocket on iOS; preserved in unsupported/shadowrocket.list. FINAL stays a parent terminal action, not a provider entry. GEOIP,CN stays typed and retains resolution behavior. No domain/IP ranges were rewritten.

| Third-party reference | Original | YAML | Choice | Reason |
|---|---:|---:|---|---|
| ACL4SSR/ACL4SSR/LocalAreaNetwork.list | 37 | 37 | yaml / classical | Ordered matcher sequence verified equal (including no-resolve) |
| ACL4SSR/ACL4SSR/UnBan.list | 31 | 52 | text / classical | Candidate differs; original typed text reference preserved |
| ACL4SSR/ACL4SSR/Download.list | 22 | 2 | text / classical | Candidate differs; original typed text reference preserved |
| blackmatrix7/ios_rule_script/Microsoft.list | 673 | 670 | text / classical | Candidate differs; original typed text reference preserved |
| blackmatrix7/ios_rule_script/DMM.list | 20 | 20 | yaml / classical | Ordered matcher sequence verified equal (including no-resolve) |
| ACL4SSR/ACL4SSR/GoogleCN.list | 29 | 48 | text / classical | Candidate differs; original typed text reference preserved |
| ACL4SSR/ACL4SSR/GoogleFCM.list | 44 | 44 | yaml / classical | Ordered matcher sequence verified equal (including no-resolve) |
| ACL4SSR/ACL4SSR/Apple.list | 29 | 29 | yaml / classical | Ordered matcher sequence verified equal (including no-resolve) |
| ACL4SSR/ACL4SSR/ProxyGFWlist.list | 6986 | 4319 | text / classical | Candidate differs; original typed text reference preserved |
| ACL4SSR/ACL4SSR/ChinaDomain.list | 635 | 635 | yaml / classical | Ordered matcher sequence verified equal (including no-resolve) |
| ACL4SSR/ACL4SSR/ChinaCompanyIp.list | 208 | 208 | yaml / ipcidr | Ordered matcher sequence verified equal (including no-resolve) |

DMM uses DMM_No_Resolve.yaml. ChinaCompanyIp uses behavior: ipcidr and no-resolve on the parent RULE-SET call; the expanded matcher sequence was compared exactly. Other YAML substitutions require the entire normalized sequence to match, including duplicate multiplicity. Different same-name YAML files are not substituted.

**Unavoidable Mihomo gaps in original third-party text:** ACL4SSR Download contains 7 URL-REGEX rules; Microsoft contains 3 USER-AGENT rules. Mihomo does not implement these matcher types. Original URLs are preserved; the core skips these entries with warnings. These are explicitly reported external compatibility gaps, not locally silently dropped rules. No YAML variant can make these types work without changing semantics. Do not treat this as complete cross-client routing equivalence.

Original third-party text is used directly by Shadowrocket; its process/regex behavior is not certified. No Shadowrocket device was available. GEOIP depends on each client's database, so database-level equivalence is outside this project.

Evidence: [subconverter inline syntax](https://github.com/tindy2013/subconverter/blob/master/README-cn.md), [Mihomo parser](https://github.com/MetaCubeX/mihomo/blob/Meta/rules/parser.go), [Mihomo classical restrictions](https://github.com/MetaCubeX/mihomo/blob/Meta/rules/provider/classical_strategy.go). Repository commit dates and content hashes for each checked external reference are in third_party_yaml_audit.json. Repo activity is observed, not a promise of future maintenance.
