"""Own-source expansion and verified third-party references, preserving occurrence order."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.parse

import yaml
from update_rules import REPOSITORY, STATUSES, fetch, json_text, normalize, parse, slug, write


def digest(data):
    return hashlib.sha256(data).hexdigest()


def typed_lines(data):
    return [(n, line.strip()) for n, line in enumerate(data.decode("utf-8-sig").splitlines(), 1)
            if line.strip() and not line.lstrip().startswith(("#", ";"))]


def comparison_rule(rule):
    """Comparison only: never mutate regex/process matcher interior whitespace."""
    return ",".join(p.strip() for p in rule.split(","))


def own_sources(root, records, metadata, offline):
    path = root / "upstream/owned_metadata.json"
    old = json.loads(path.read_text("utf-8")) if path.exists() else []
    old_by_url = {r["url"]: r for r in old}
    references = [r for r in records if r["status"] == "EXTERNAL_DEPENDENCY" and r["url"].startswith(f"https://raw.githubusercontent.com/{REPOSITORY}/")]
    output = []
    for ref in references:
        url = ref["url"]
        if offline:
            if url not in old_by_url:
                raise ValueError(f"Missing frozen owned source: {url}; run online once")
            entry = old_by_url[url]
            if entry["commit"] != metadata["commit"]:
                raise ValueError("Owned snapshots do not match the template commit")
        else:
            prefix = f"https://raw.githubusercontent.com/{REPOSITORY}/master/"
            if not url.startswith(prefix):
                raise ValueError("New owned branch/path requires explicit review")
            relative = url.removeprefix(prefix)
            pinned = f"https://raw.githubusercontent.com/{REPOSITORY}/{metadata['commit']}/{relative}"
            data = fetch(pinned)
            data.decode("utf-8-sig")  # fail rather than silently replace undecodable bytes
            target = f"upstream/owned/{digest(data)}/{Path(relative).name}"
            if (root / target).exists() and (root / target).read_bytes() != data:
                raise ValueError("Refusing to overwrite an existing owned snapshot")
            write(root / target, data)
            entry = {"url": url, "pinned_url": pinned, "repository": REPOSITORY,
                     "branch": "master", "commit": metadata["commit"], "sha256": digest(data),
                     "fetched_at": datetime.now(timezone.utc).isoformat(), "snapshot": target, "policy": ref["policy"], "parent_line": ref["line"]}
            if url in old_by_url and old_by_url[url]["sha256"] == entry["sha256"]:
                entry["fetched_at"] = old_by_url[url]["fetched_at"]
        data = (root / entry["snapshot"]).read_bytes()
        if digest(data) != entry["sha256"]:
            raise ValueError("Owned snapshot checksum mismatch")
        output.append((entry, data))
    if not offline:
        write(path, json_text([entry for entry, _ in output]))
    return output


def candidate_path(repository, path):
    if repository == "ACL4SSR/ACL4SSR":
        if path == "Clash/GoogleCN.list":
            return "Clash/Providers/Ruleset/GoogleCN.yaml"
        return path.replace("Clash/", "Clash/Providers/", 1).removesuffix(".list") + ".yaml"
    if repository == "blackmatrix7/ios_rule_script":
        target = path.replace("/Surge/", "/Clash/").removesuffix(".list")
        return target + ("_No_Resolve.yaml" if "/DMM/" in path else ".yaml")
    raise ValueError("New external repository requires a reviewed YAML mapping")


def verify_external(root, references, offline, refresh_vendored=False):
    lock = root / "upstream/external_metadata.json"
    if offline:
        evidence = json.loads(lock.read_text("utf-8"))
        if [r["url"] for r in evidence] != [r["url"] for r in references]:
            raise ValueError("External reference set changed; online re-verification required")
        return evidence
    vendor_path = root / "upstream/vendor_metadata.json"
    frozen_urls = {r["url"] for r in json.loads(vendor_path.read_text("utf-8"))} if vendor_path.exists() and not refresh_vendored else set()
    cached = {r["url"]: r for r in json.loads(lock.read_text("utf-8"))} if lock.exists() else {}
    repositories = list(dict.fromkeys("/".join(r["url"].split("/")[3:5]) for r in references if r["url"] not in frozen_urls))
    heads = {repo: json.loads(fetch(f"https://api.github.com/repos/{repo}/commits/master")) for repo in repositories}
    def verify(ref):
        if ref["url"] in frozen_urls:
            return {**cached[ref["url"]], "policy": ref["policy"], "parent_line": ref["line"]}
        _, _, _, owner, repo, branch, *rest = ref["url"].split("/")
        repository, path = owner + "/" + repo, "/".join(rest)
        target = candidate_path(repository, path)
        head = heads[repository]
        base = f"https://raw.githubusercontent.com/{repository}/{head['sha']}/"
        original, converted = fetch(base + path), fetch(base + target)
        source = [comparison_rule(l) for _, l in typed_lines(original)]
        document = yaml.safe_load(converted)
        if not isinstance(document, dict) or not isinstance(document.get("payload"), list) or not all(isinstance(r, str) for r in document["payload"]):
            raise ValueError("External YAML is not a string payload list")
        payload = [comparison_rule(r) for r in document["payload"]]
        behavior, call_params = "classical", []
        expanded = payload
        if path == "Clash/ChinaCompanyIp.list":
            import ipaddress
            for r in payload:
                ipaddress.ip_network(r, strict=False)
            expanded = ["IP-CIDR," + r + ",no-resolve" for r in payload]
            behavior, call_params = "ipcidr", ["no-resolve"]
        equivalent = source == expanded
        selected_url = f"https://raw.githubusercontent.com/{repository}/master/{target}" if equivalent else ref["url"]
        # Unsupported third-party matcher lines are evidence only, never materialized as local datasets.
        unsupported = [{"line": n, "rule": l, "reason": "Not supported by Mihomo classical parser"}
                       for n, l in typed_lines(original) if l.split(",", 1)[0] in {"URL-REGEX", "USER-AGENT"}]
        item = {"url": ref["url"], "policy": ref["policy"], "parent_line": ref["line"],
                "repository": repository, "commit": head["sha"], "repository_last_commit_at": head["commit"]["committer"]["date"],
                "yaml_candidate_url": f"https://raw.githubusercontent.com/{repository}/master/{target}",
                "original_sha256": digest(original), "yaml_sha256": digest(converted),
                "original_count": len(source), "yaml_count": len(payload), "ordered_equal": equivalent,
                "selected_url": selected_url, "format": "yaml" if equivalent else "text",
                "behavior": behavior if equivalent else "classical", "call_params": call_params if equivalent else [],
                "reason": "Ordered matcher sequence verified equal (including no-resolve)" if equivalent else "Candidate differs; original typed text reference preserved",
                "only_original_count": sum((Counter(source) - Counter(expanded)).values()),
                "only_yaml_count": sum((Counter(expanded) - Counter(source)).values()),
                "mihomo_unsupported": unsupported, "materialized": False,
                "maintenance_note": "Repository head activity observed; future availability or per-file maintenance not guaranteed"}
        return item
    with ThreadPoolExecutor(max_workers=4) as pool:
        evidence = list(pool.map(verify, references))
    write(lock, json_text(evidence))
    return evidence


def provider_yaml(values):
    return "payload:\n" + "".join("  - " + json.dumps(r, ensure_ascii=False) + "\n" for r in values)


def extend_project(root, source, metadata, files, raw_base, offline=False, refresh_vendored=False):
    parents = parse(source)[1]
    owned = own_sources(root, parents, metadata, offline)
    own_by_line = {m["parent_line"]: (m, data) for m, data in owned}
    third = verify_external(root, [r for r in parents if r["status"] == "EXTERNAL_DEPENDENCY" and r["line"] not in own_by_line], offline, refresh_vendored)
    third_by_line = {r["parent_line"]: r for r in third}
    # Replace base projections with expanded projections, while retaining original 4.ini audit.
    files = {k: v for k, v in files.items() if not k.startswith(("canonical/", "mihomo/", "shadowrocket/", "unsupported/"))}
    records, source_audits, sequence = [], [], []
    for parent in parents:
        if parent["line"] in own_by_line:
            m, data = own_by_line[parent["line"]]
            entries = []
            for number, original in typed_lines(data):
                matcher, status, reason = normalize(original)
                r = {"id": f"{parent['line']}:{number}", "file": m["snapshot"], "line": number,
                     "parent_line": parent["line"], "policy": parent["policy"], "raw": original,
                     "matcher": matcher, "type": matcher.split(",", 1)[0], "status": status, "reason": reason,
                     "normalizations": [] if matcher == original else [{"before": original, "after": matcher, "reason": "Delimiter whitespace and type only"}],
                     "targets": {"mihomo": status, "shadowrocket": "UNSUPPORTED" if matcher.startswith("PROCESS-NAME,") else status}}
                entries.append(r)
            source_audits.append({"source": m, "total_lines": len(data.decode("utf-8-sig").splitlines()),
                                  "blank_lines": sum(not l.strip() for l in data.decode("utf-8-sig").splitlines()),
                                  "comments": sum(l.lstrip().startswith(("#", ";")) for l in data.decode("utf-8-sig").splitlines()),
                                  "rule_count": len(entries), "policy_inherited_from_4_ini_line": parent["line"],
                                  "rule_type_counts": dict(Counter(r["type"] for r in entries)),
                                  "accounting": {s.lower(): sum(r["status"] == s for r in entries) for s in STATUSES}})
            name = f"{parent['line']:03d}-{Path(m['snapshot']).stem.lower()}"
            sequence.append({"parent_line": parent["line"], "kind": "owned", "policy": parent["policy"], "segment": name,
                             "record_ids": [r["id"] for r in entries]})
            records.extend(entries)
        elif parent["status"] == "EXTERNAL_DEPENDENCY":
            sequence.append({"parent_line": parent["line"], "kind": "external", "policy": parent["policy"], "dependency": third_by_line[parent["line"]]})
        else:
            r = {**parent, "id": f"{parent['line']}:0", "file": metadata["snapshot"], "parent_line": parent["line"],
                 "targets": {"mihomo": parent["status"], "shadowrocket": parent["status"]}}
            records.append(r)
            sequence.append({"parent_line": parent["line"], "kind": "inline", "policy": parent["policy"], "segment": f"{parent['line']:03d}-inline", "record_ids": [r["id"]]})
    by_id = {r["id"]: r for r in records}
    # Internal per-source and per-policy projections all preserve list order and multiplicity.
    inventory = []
    def emit(path, values, purpose):
        if not values:
            return
        files[path] = provider_yaml(values) if path.endswith(".yaml") else "\n".join(values) + "\n"
        inventory.append({"file": path, "rules": len(values), "purpose": purpose})
    policy_map = {p: slug(p) for p in dict.fromkeys(r["policy"] for r in records if r["status"] == "GENERATED")}
    for policy, name in policy_map.items():
        group = [r for r in records if r["policy"] == policy and r["status"] == "GENERATED"]
        emit(f"canonical/{name}.list", [r["matcher"] for r in group], "Policy projection; do not use to reorder global calls")
        for target, suffix in (("mihomo", "yaml"), ("shadowrocket", "list")):
            emit(f"{target}/{name}.{suffix}", [r["matcher"] for r in group if r["targets"][target] == "GENERATED"], "Policy projection")
    for segment in sequence:
        if segment["kind"] == "external":
            continue
        entries = [by_id[i] for i in segment["record_ids"]]
        for target, suffix in (("mihomo", "yaml"), ("shadowrocket", "list")):
            emit(f"{target}/segments/{segment['segment']}.{suffix}", [r["matcher"] for r in entries if r["targets"][target] == "GENERATED"], "Ordered usage segment")
    for target in ("mihomo", "shadowrocket"):
        held = [r for r in records if r["targets"][target] != "GENERATED"]
        if held:
            files[f"unsupported/{target}.list"] = "".join(f"# {r['file']}:{r['line']}; policy={r['policy']}; {r['targets'][target]}\n{r['matcher']}\n" for r in held)
    held = [r for r in records if r["status"] != "GENERATED"]
    if held:
        files["canonical/unsupported.list"] = "".join(f"# {r['file']}:{r['line']}; policy={r['policy']}; {r['reason']}\n{r['matcher']}\n" for r in held)
    uncertain = [r for r in records if r["status"] in {"AMBIGUOUS", "INVALID_WITH_EVIDENCE"}]
    if uncertain:
        files["unsupported/ambiguous.list"] = "".join(f"# {r['id']}; {r['reason']}\n{r['raw']}\n" for r in uncertain)
    duplicates, seen, by_matcher = [], {}, defaultdict(list)
    for r in records:
        key = (r["policy"], r["matcher"])
        if key in seen:
            duplicates.append({"occurrence": r["id"], "first_occurrence": seen[key], "matcher": r["matcher"], "policy": r["policy"], "action": "PRESERVED"})
        else:
            seen[key] = r["id"]
        by_matcher[r["matcher"]].append({"id": r["id"], "policy": r["policy"], "file": r["file"], "line": r["line"]})
    conflicts = [{"matcher": m, "occurrences": rs} for m, rs in by_matcher.items() if len({r["policy"] for r in rs}) > 1]
    statuses = Counter(r["status"] for r in records)
    totals = {"input_valid_rules": len(records) + len(third), **{s.lower(): statuses[s] for s in STATUSES}, "unexplained_loss": 0}
    totals["external_dependency"] += len(third)
    totals["definition"] = "Expanded leaf rules: 9 owned references replaced by their rule occurrences; 11 third-party references remain opaque dependency units. Original 22-declaration accounting is retained separately."
    ledger = {"totals": totals, "local_records": records, "external_records": third,
              "per_target": {t: {s.lower(): sum(r["targets"][t] == s for r in records) for s in STATUSES} for t in ("mihomo", "shadowrocket")}}
    files["canonical/ordered.json"] = json_text({"description": "Canonical truth: local leaf records + unexpanded third-party dependencies + original ordered calls", "records": records, "sequence": sequence})
    files["artifacts/expanded_source_accounting.json"] = json_text(ledger)
    files["artifacts/owned_source_audit.json"] = json_text(source_audits)
    files["artifacts/dedup_report.json"] = json_text({"mode": "INFORMATIONAL_ONLY", "exact_duplicate_count": len(duplicates), "exact_duplicates_removed": 0, "semantic_duplicates_removed": 0, "semantic_analysis": "DISABLED_BY_USER", "preserved_duplicates": duplicates, "removed_rules": []})
    files["artifacts/conflicts.json"] = json_text({"mode": "INFORMATIONAL_ONLY", "same_matcher_multiple_policy_count": len(conflicts), "items": conflicts})
    files["artifacts/normalization_report.json"] = json_text([{ "id": r["id"], "changes": r["normalizations"]} for r in records if r["normalizations"]])
    files["artifacts/policy_mapping.json"] = json_text(policy_map)
    files["artifacts/generated_counts.json"] = json_text(inventory)
    files["artifacts/external_dependencies.json"] = json_text(third)
    files["artifacts/materialized_dependencies.json"] = json_text([m for m, _ in owned])
    files["artifacts/third_party_yaml_audit.json"] = json_text(third)
    # Original accounting explicitly links materialized references instead of double counting them.
    original_ledger = json.loads(files["artifacts/source_accounting.json"])
    for r in original_ledger["records"]:
        if r["line"] in own_by_line:
            r["materialized"] = True
            r["child_ids"] = [leaf["id"] for leaf in records if leaf["parent_line"] == r["line"]]
            r["reason"] = "Owned dependency materialized after explicit user request; child accounting separate"
    files["artifacts/source_accounting.json"] = json_text(original_ledger)
    audit_md = "# Owned source audit\n\nAll nine owned files were read in full before conversion. Policy inherited exclusively from their active 4.ini reference.\n\n| File | Rules | Policy | Source line |\n|---|---:|---|---:|\n"
    audit_md += "".join(f"| {Path(a['source']['snapshot']).name} | {a['rule_count']} | {a['source']['policy']} | {a['source']['parent_line']} |\n" for a in source_audits)
    audit_md += "\nRule types: " + json.dumps(dict(Counter(r["type"] for r in records)), ensure_ascii=False) + ".\n\n"
    audit_md += "Policies (local leaf occurrences): " + json.dumps(dict(Counter(r["policy"] for r in records)), ensure_ascii=False) + ".\n\n"
    audit_md += f"Exact duplicate occurrences {len(duplicates)}; same matcher multiple policies {len(conflicts)}. All retained; no semantic coverage analysis. See dedup_report.json and conflicts.json for every source location. No matcher rewrite; dotted numeric DOMAIN-SUFFIX values retain their original type. Windows process names retain internal spaces.\n\n"
    audit_md += "Expanded SOURCE_ACCOUNTING: " + str(totals["input_valid_rules"]) + " = " + " + ".join(str(totals[s.lower()]) for s in STATUSES) + ".\n"
    files["artifacts/owned_source_audit.md"] = audit_md
    files["artifacts/source_audit.md"] += "\n## Expanded scope\n\nLater user instruction explicitly authorized materializing the nine Ghou133-owned references. See [owned_source_audit.md](owned_source_audit.md) and expanded_source_accounting.json. Third-party content was fetched only transiently to compare YAML candidates; it was not copied into generated datasets. Original 4.ini counts above remain unchanged.\n"
    compatibility = "# Compatibility and third-party YAML audit\n\nOwn-source PROCESS-NAME is emitted for Mihomo only. Eight Windows process rules cannot be represented reliably by Shadowrocket on iOS; preserved in unsupported/shadowrocket.list. FINAL stays a parent terminal action, not a provider entry. GEOIP,CN stays typed and retains resolution behavior. No domain/IP ranges were rewritten.\n\n"
    compatibility += "| Third-party reference | Original | YAML | Choice | Reason |\n|---|---:|---:|---|---|\n"
    compatibility += "".join(f"| {r['repository']}/{Path(r['url']).name} | {r['original_count']} | {r['yaml_count']} | {r['format']} / {r['behavior']} | {r['reason']} |\n" for r in third)
    compatibility += "\nDMM uses DMM_No_Resolve.yaml. ChinaCompanyIp uses behavior: ipcidr and no-resolve on the parent RULE-SET call; the expanded matcher sequence was compared exactly. Other YAML substitutions require the entire normalized sequence to match, including duplicate multiplicity. Different same-name YAML files are not substituted.\n\n"
    compatibility += "**Unavoidable Mihomo gaps in original third-party text:** ACL4SSR Download contains 7 URL-REGEX rules; Microsoft contains 3 USER-AGENT rules. Mihomo does not implement these matcher types. Original URLs are preserved; the core skips these entries with warnings. These are explicitly reported external compatibility gaps, not locally silently dropped rules. No YAML variant can make these types work without changing semantics. Do not treat this as complete cross-client routing equivalence.\n\n"
    compatibility += "Original third-party text is used directly by Shadowrocket; its process/regex behavior is not certified. No Shadowrocket device was available. GEOIP depends on each client's database, so database-level equivalence is outside this project.\n\n"
    compatibility += "Evidence: [subconverter inline syntax](https://github.com/tindy2013/subconverter/blob/master/README-cn.md), [Mihomo parser](https://github.com/MetaCubeX/mihomo/blob/Meta/rules/parser.go), [Mihomo classical restrictions](https://github.com/MetaCubeX/mihomo/blob/Meta/rules/provider/classical_strategy.go). Repository commit dates and content hashes for each checked external reference are in third_party_yaml_audit.json. Repo activity is observed, not a promise of future maintenance.\n"
    files["artifacts/compatibility_report.md"] = compatibility
    mh, sr = usage(sequence, by_id, raw_base)
    files["examples/mihomo-rules.yaml"] = mh
    files["examples/shadowrocket-rules.list"] = sr
    table = "| File | Format | Rules | Purpose |\n|---|---|---:|---|\n"
    for i in inventory:
        if "/segments/" not in i["file"]:
            table += f"| [{i['file']}]({i['file']}) | {'YAML' if i['file'].endswith('.yaml') else 'typed list'} | {i['rules']} | {i['purpose']} |\n"
    files["README.md"] = f"""# Rule Sets

你的历史规则规范化仓库：保留重复、匹配范围、原策略与源顺序。仅提供规则数据和引用片段，不包含节点、订阅、代理组、DNS 或完整主配置。

## Upstream

[{metadata['url']}]({metadata['url']})

Commit: `{metadata['commit']}`

SHA-256: `{metadata['sha256']}`

`4.ini` 有 22 个规则声明：9 个你仓库内的引用已冻结、完整审计并转换；11 个第三方引用直接使用其远程文件；另有 GEOIP 和 FINAL。各冻结文件的 commit、SHA-256、下载时间见 upstream/*metadata.json。原始 4.ini 永不覆盖。

## Generated Files

{table}

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
    url: {raw_base}/mihomo/segments/005-boost.yaml
    path: ./ruleset/own-boost.yaml
    interval: 86400
rules:
  - RULE-SET,own-boost,<YOUR_POLICY_FOR_Proxies>
```

`<YOUR_POLICY_FOR_...>` 必须替换为你已有策略名；没有创建任何代理组。`Proxies`、`DMM`、`Japan`、`Hongkong`、`Others` 保留为独立策略，不擅自合并成 PROXY。完整示例最后将原 FINAL 表达为父级 MATCH。

## Shadowrocket Usage

[完整保序片段](examples/shadowrocket-rules.list)使用原第三方文本与自有 typed RULE-SET 文件。例如：

```text
RULE-SET,{raw_base}/shadowrocket/segments/005-boost.list,<YOUR_POLICY_FOR_Proxies>
```

不是 DOMAIN-SET。自有 Windows PROCESS-NAME 共 8 条保留在 unsupported/shadowrocket.list；未做 iOS 实机验证。

## Statistics

本地有效叶子规则 {len(records)}；生成 {totals['generated']}；unsupported {totals['unsupported']}；ambiguous {totals['ambiguous']}；invalid {totals['invalid_with_evidence']}。第三方依赖 {len(third)}。扩展账本：**{totals['input_valid_rules']} = {' + '.join(str(totals[s.lower()]) for s in STATUSES)}**（generated + unsupported + ambiguous + external_dependency + invalid_with_evidence）。原模板 22 个声明另有独立账本，容器引用与叶子规则不重复相加。

Exact duplicates {len(duplicates)}，全部保留、删除 0；semantic dedup 禁用；同 matcher 多 policy {len(conflicts)}，仅观察、全部保留。完整位置见 [dedup_report.json](artifacts/dedup_report.json) / [conflicts.json](artifacts/conflicts.json)。

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
"""
    from vendor_rules import materialize
    return materialize(root, files, third, raw_base, offline, refresh_vendored)


def usage(sequence, records, raw_base):
    providers, calls, sr = {}, [], []
    for step in sequence:
        line, policy = step["parent_line"], step["policy"]
        action = policy if policy in {"DIRECT", "REJECT"} else f"<YOUR_POLICY_FOR_{policy}>"
        name = f"source-{line:03d}"
        if step["kind"] == "external":
            d = step["dependency"]
            providers[name] = {"type": "http", "behavior": d["behavior"], "format": d["format"], "url": d["selected_url"],
                               "path": f"./ruleset/{name}.{'yaml' if d['format'] == 'yaml' else 'list'}", "interval": 86400}
            calls.append(f"RULE-SET,{name},{action}" + ("," + ",".join(d["call_params"]) if d["call_params"] else ""))
            sr.append(f"RULE-SET,{d['url']},{action}")
        else:
            entries = [records[i] for i in step["record_ids"]]
            if any(r["targets"]["mihomo"] == "GENERATED" for r in entries):
                providers[name] = {"type": "http", "behavior": "classical", "format": "yaml", "url": f"{raw_base}/mihomo/segments/{step['segment']}.yaml",
                                   "path": f"./ruleset/{name}.yaml", "interval": 86400}
                calls.append(f"RULE-SET,{name},{action}")
            if any(r["targets"]["shadowrocket"] == "GENERATED" for r in entries):
                sr.append(f"RULE-SET,{raw_base}/shadowrocket/segments/{step['segment']}.list,{action}")
            for r in entries:
                if r["matcher"] in {"FINAL", "MATCH"}:
                    calls.append("MATCH," + action)
                    sr.append("FINAL," + action)
    mh = "# Rules-only fragment. Replace explicit policy/raw placeholders.\n# Original external text includes 10 unsupported Mihomo rules; see compatibility report.\n"
    mh += yaml.safe_dump({"rule-providers": providers, "rules": calls}, allow_unicode=True, sort_keys=False, width=200)
    return mh, "# Preserve this call order. Replace explicit policy/raw placeholders.\n" + "\n".join(sr) + "\n"


def validate_project(files):
    ordered = json.loads(files["canonical/ordered.json"])
    records = ordered["records"]
    assert len({r["id"] for r in records}) == len(records)
    ledger = json.loads(files["artifacts/expanded_source_accounting.json"])
    totals = ledger["totals"]
    assert totals["input_valid_rules"] == sum(totals[s.lower()] for s in STATUSES)
    assert len(records) + len(ledger["external_records"]) == totals["input_valid_rules"]
    mapping = json.loads(files["artifacts/policy_mapping.json"])
    for policy, name in mapping.items():
        group = [r for r in records if r["policy"] == policy and r["status"] == "GENERATED"]
        assert files[f"canonical/{name}.list"].splitlines() == [r["matcher"] for r in group]
        for target, suffix in (("mihomo", "yaml"), ("shadowrocket", "list")):
            expected = [r["matcher"] for r in group if r["targets"][target] == "GENERATED"]
            if expected:
                text = files[f"{target}/{name}.{suffix}"]
                actual = yaml.safe_load(text)["payload"] if suffix == "yaml" else text.splitlines()
                assert isinstance(actual, list) and actual == expected
    for path, text in files.items():
        assert text.endswith("\n") and "\r" not in text and not text.startswith("\ufeff"), path
        if path.startswith("mihomo/"):
            payload = yaml.safe_load(text)["payload"]
            assert isinstance(payload, list)
            for rule in payload:
                assert normalize(rule)[1] == "GENERATED", (path, rule)
    for r in records:
        for target in ("mihomo", "shadowrocket"):
            assert r["targets"][target] in STATUSES
    assert [s["parent_line"] for s in ordered["sequence"]] == sorted(s["parent_line"] for s in ordered["sequence"])
