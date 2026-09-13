#!/usr/bin/env python3
"""Conservative importer: expand only authorized sources; never sort or deduplicate."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Ghou133/Ghou133.github.io"
BRANCH = "master"
URL = f"https://raw.githubusercontent.com/{REPOSITORY}/refs/heads/{BRANCH}/archives/4.ini"
TYPES = "DOMAIN DOMAIN-SUFFIX DOMAIN-KEYWORD IP-CIDR IP-CIDR6 IP-ASN GEOIP USER-AGENT URL-REGEX PROCESS-NAME PROCESS-PATH DEST-PORT DST-PORT SRC-IP-CIDR AND OR NOT RULE-SET FINAL MATCH".split()
STATUSES = "GENERATED UNSUPPORTED AMBIGUOUS EXTERNAL_DEPENDENCY INVALID_WITH_EVIDENCE".split()
SUPPORTED = {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "IP-CIDR", "IP-CIDR6", "GEOIP", "PROCESS-NAME"}
CONFIG_KEYS = {"custom_proxy_group", "enable_rule_generator", "overwrite_original_rules"}


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = data.encode("utf-8") if isinstance(data, str) else data
    if not path.exists() or path.read_bytes() != data:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "proxy-rule-sets-importer", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(10_000_001)
    if not data or len(data) > 10_000_000:
        raise ValueError("Empty or unexpectedly large response")
    return data


def snapshot(root):
    """Pin before download; immutable initial snapshot plus content-addressed updates."""
    api = f"https://api.github.com/repos/{REPOSITORY}"
    commit = json.loads(fetch(api + f"/commits/{BRANCH}"))["sha"]
    data = fetch(f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/archives/4.ini")
    decoded = data.decode("utf-8-sig")
    if "[custom]" not in decoded or "ruleset=" not in decoded:
        raise ValueError("Not an expected subconverter custom template; no files changed")
    tree = json.loads(fetch(api + f"/git/trees/{commit}?recursive=1"))
    if tree.get("truncated"):
        raise ValueError("License scan incomplete: GitHub tree truncated")
    license_paths = [item["path"] for item in tree["tree"] if item["type"] == "blob" and re.match(r"^(licen[cs]e|copying)(\.|$)", Path(item["path"]).name, re.I)]
    license_data = [(p, fetch(f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{p}")) for p in license_paths]
    digest = hashlib.sha256(data).hexdigest()
    active = root / "upstream/metadata.json"
    if active.exists():
        old = json.loads(active.read_text("utf-8"))
        if old["sha256"] == digest and old["commit"] == commit:
            return old
        relative = f"upstream/snapshots/{digest}/4.ini"
    else:
        relative = "upstream/4.ini"
    metadata = {
        "url": URL, "repository": REPOSITORY, "branch": BRANCH, "commit": commit,
        "sha256": digest, "fetched_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": relative,
        "pinned_url": f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/archives/4.ini",
        "license": {"status": "FOUND_REQUIRES_REVIEW" if license_paths else "NOT_DECLARED", "paths": license_paths, "scope": "complete recursive repository tree; LICENSE/LICENCE/COPYING filenames"},
    }
    destination = root / relative
    if destination.exists() and destination.read_bytes() != data:
        raise ValueError("Refusing to overwrite frozen snapshot")
    write(destination, data)
    write(destination.parent / "snapshot-metadata.json", json_text(metadata))
    for name, contents in license_data:
        write(destination.parent / "licenses" / name, contents)
    write(active, json_text(metadata))
    return metadata


def normalize(text):
    """Only verified, simple grammars. Unknown/compound strings remain intact."""
    tp = text.split(",", 1)[0].strip().upper()
    if tp not in SUPPORTED | {"FINAL", "MATCH"}:
        return text.strip(), "UNSUPPORTED", "Unreviewed rule grammar; retained verbatim"
    fields = [field.strip() for field in text.split(",")]
    fields[0] = tp
    result = ",".join(fields)
    if tp in {"FINAL", "MATCH"}:
        if len(fields) != 1:
            return result, "INVALID_WITH_EVIDENCE", "Terminal rule must not have inline arguments"
        return result, "UNSUPPORTED", "Terminal action belongs in parent rules, not a portable rule-provider"
    if len(fields) < 2 or not fields[1]:
        return result, "INVALID_WITH_EVIDENCE", "Missing matcher"
    if len(fields) > 3 or (len(fields) == 3 and fields[2].lower() != "no-resolve"):
        return result, "AMBIGUOUS", "Unknown arguments; possible embedded policy; not stripped"
    if len(fields) == 3:
        if tp not in {"IP-CIDR", "IP-CIDR6", "GEOIP"}:
            return result, "AMBIGUOUS", "no-resolve is not applicable to this audited matcher type"
        fields[2] = "no-resolve"
    value = fields[1]
    if tp.startswith("DOMAIN"):
        if any(c.isspace() for c in value) or any(c in value for c in "/\\:"):
            return result, "INVALID_WITH_EVIDENCE", "Domain matcher contains URL/path/whitespace characters"
        if any(c in value for c in "*?[]") or not value.isascii():
            return result, "AMBIGUOUS", "Wildcard or internationalized domain semantics require review"
        # Preserve original domain text: no lowercasing, suffix folding or IDNA rewrite.
    if tp in {"IP-CIDR", "IP-CIDR6"}:
        try:
            parsed = ipaddress.ip_network(value, strict=False)
            if parsed.version != (4 if tp == "IP-CIDR" else 6):
                raise ValueError("address-family mismatch")
        except ValueError as error:
            return result, "INVALID_WITH_EVIDENCE", str(error)
        # Validate but DO NOT rewrite host bits or lexical representation.
    if tp == "GEOIP" and not re.fullmatch(r"[A-Z]{2}", value):
        return result, "AMBIGUOUS", "Only two-letter uppercase country GEOIP audited"
    return ",".join(fields), "GENERATED", "Policyless provider rule; matcher preserved"


def parse(source):
    lines = source.decode("utf-8-sig").splitlines()
    records, sections, non_rules, comments, unknown = [], [], [], [], []
    section = None
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("#", ";")):
            comments.append(number)
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            sections.append({"line": number, "name": section})
            continue
        key, separator, value = line.partition("=")
        if key.strip() in CONFIG_KEYS and separator:
            non_rules.append({"line": number, "key": key.strip(), "reason": "Non-rule configuration outside project scope"})
            continue
        if key.strip().lower() != "ruleset" or not separator:
            unknown.append({"line": number, "raw": raw, "reason": "Unrecognized non-comment syntax; quarantined for review"})
            records.append({"line": number, "raw": raw, "policy": None, "type": "UNKNOWN", "matcher": line, "status": "AMBIGUOUS", "reason": "Unrecognized source syntax", "normalizations": []})
            continue
        policy, comma, expression = value.partition(",")
        policy, expression = policy.strip(), expression.strip()
        record = {"line": number, "raw": raw, "policy": policy or None, "normalizations": [], "type": "UNKNOWN", "matcher": expression}
        if not comma or not expression:
            record.update(status="INVALID_WITH_EVIDENCE", reason="ruleset requires policy and expression")
        elif section != "custom":
            record.update(status="AMBIGUOUS", reason="ruleset outside audited [custom] section")
        elif expression.startswith(("https://", "http://")):
            from urllib.parse import urlsplit
            parsed = urlsplit(expression)
            record.update(type="RULE-SET", url=expression)
            if not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in expression) or "," in expression:
                record.update(status="AMBIGUOUS", reason="External URL/options require manual review")
            else:
                record.update(matcher="RULE-SET," + expression, status="EXTERNAL_DEPENDENCY", reason="External content not fetched or materialized")
        elif expression.startswith("[]"):
            original = expression[2:]
            matcher, status, reason = normalize(original)
            record.update(type=matcher.split(",", 1)[0].upper(), matcher=matcher, status=status, reason=reason)
            record["normalizations"].append("Removed subconverter [] inline marker; policy retained separately")
            if matcher != original:
                record["normalizations"].append({"before": original, "after": matcher, "reason": "Rule type and delimiter whitespace only"})
        else:
            record.update(status="AMBIGUOUS", reason="Local dependency or unreviewed subconverter expression; retained")
        if not policy and record["status"] != "INVALID_WITH_EVIDENCE":
            record.update(status="AMBIGUOUS", reason="No explicit policy; no routing policy inferred")
        records.append(record)
    return lines, records, sections, non_rules, comments, unknown


def audit_source(source):
    lines, records, sections, non_rules, comments, unknown = parse(source)
    duplicates, conflicts, seen, matchers = [], [], {}, defaultdict(list)
    for r in records:
        key = (r["policy"], r["matcher"])
        if key in seen:
            duplicates.append({"line": r["line"], "first_line": seen[key], "matcher": r["matcher"], "policy": r["policy"], "action": "PRESERVED"})
        else:
            seen[key] = r["line"]
        matchers[r["matcher"]].append({"line": r["line"], "policy": r["policy"]})
    for matcher, locations in matchers.items():
        if len({r["policy"] for r in locations}) > 1:
            conflicts.append({"matcher": matcher, "locations": locations, "action": "INFORMATIONAL_ONLY; source order preserved"})
    statuses = Counter(r["status"] for r in records)
    accounting = {"input_valid_rules": len(records), **{key.lower(): statuses[key] for key in STATUSES}, "unexplained_loss": 0,
                  "definition": "All active rule declarations, including invalid candidates and unknown syntax conservatively accounted; excludes comments/sections/known non-rule config"}
    counts = Counter(r["type"] for r in records)
    audit = {
        "total_lines": len(lines), "blank_lines": sum(not l.strip() for l in lines), "comment_lines": len(comments),
        "comment_locations": comments, "sections": sections, "valid_rules": len(records),
        "rule_type_counts": {tp: counts[tp] for tp in dict.fromkeys(TYPES + list(counts))},
        "policy_counts": dict(Counter(r["policy"] or "UNCLASSIFIED" for r in records)),
        "non_rule_config": non_rules, "unknown_syntax": unknown,
        "invalid_lines": [r for r in records if r["status"] == "INVALID_WITH_EVIDENCE"],
        "policyless_rules": [r["line"] for r in records if not r["policy"]],
        "unsupported_rules": [r["line"] for r in records if r["status"] == "UNSUPPORTED"],
        "no_resolve_count": sum(r["matcher"].endswith(",no-resolve") for r in records),
        "exact_duplicate_count": len(duplicates), "same_matcher_multiple_policy_count": len(conflicts),
        "order": "PRESERVE SOURCE ORDER; no sorting, deduplication or conflict resolution",
        "source_accounting": accounting,
    }
    return audit, records, duplicates, conflicts


def slug(policy):
    if policy in {"DIRECT", "PROXY", "REJECT"}:
        return policy.lower()
    if policy in {"Proxies", "DMM", "Japan", "Hongkong", "Others"}:
        return policy.lower()
    basic = re.sub(r"[^a-z0-9]+", "-", policy.lower()).strip("-") or "policy"
    # Names differing only in punctuation/case must never merge.
    return basic + "-" + hashlib.sha256(policy.encode()).hexdigest()[:8]


def build(source, metadata, raw_base="<GITHUB_RAW_BASE>"):
    audit, records, duplicates, conflicts = audit_source(source)
    files = {}
    def put(path, content):
        files[path] = content
    def js(path, content):
        put(path, json_text(content))
    js("artifacts/source_audit.json", audit)
    js("artifacts/source_accounting.json", {"totals": audit["source_accounting"], "records": records})
    js("artifacts/conflicts.json", {"mode": "INFORMATIONAL_ONLY", "same_matcher_multiple_policy_count": len(conflicts), "items": conflicts})
    js("artifacts/dedup_report.json", {"mode": "INFORMATIONAL_ONLY", "exact_duplicate_count": len(duplicates), "exact_duplicates_removed": 0, "semantic_duplicates_removed": 0, "semantic_analysis": "DISABLED_BY_USER", "removed_rules": [], "preserved_duplicates": duplicates})
    js("artifacts/external_dependencies.json", [{"url": r["url"], "policy": r["policy"], "line": r["line"], "materialized": False} for r in records if r["status"] == "EXTERNAL_DEPENDENCY"])
    js("artifacts/normalization_report.json", [{"line": r["line"], "changes": r["normalizations"]} for r in records if r["normalizations"]])
    js("canonical/ordered.json", {"description": "Canonical ordered truth; lists and providers are projections. Every occurrence retains its source line and policy.", "rules": records})
    groups = defaultdict(list)
    held = defaultdict(list)
    for r in records:
        if r["status"] == "GENERATED":
            groups[r["policy"]].append(r)
        elif r["status"] != "EXTERNAL_DEPENDENCY":
            held[r["status"]].append(r)
    mapping = {policy: slug(policy) for policy in groups}
    js("artifacts/policy_mapping.json", mapping)
    for policy, entries in groups.items():
        name = mapping[policy]
        values = [r["matcher"] for r in entries]
        put(f"canonical/{name}.list", "\n".join(values) + "\n")
        put(f"shadowrocket/{name}.list", "\n".join(values) + "\n")
        # JSON string quoting is a valid YAML scalar and escapes special tokens safely.
        put(f"mihomo/{name}.yaml", "payload:\n" + "".join("  - " + json.dumps(v, ensure_ascii=False) + "\n" for v in values))
    for status, entries in held.items():
        name = "unsupported" if status == "UNSUPPORTED" else "unclassified"
        existing = files.get(f"canonical/{name}.list", "")
        text = "".join(f"# source line {r['line']}; policy={r['policy']}; {r['reason']}\n{r['matcher']}\n" for r in entries)
        put(f"canonical/{name}.list", existing + text)
    unsupported = held.get("UNSUPPORTED", [])
    if unsupported:
        text = "".join(f"# line {r['line']}; original policy: {r['policy']}; {r['reason']}\n{r['matcher']}\n" for r in unsupported)
        put("unsupported/mihomo.list", text)
        put("unsupported/shadowrocket.list", text)
    uncertain = [r for r in records if r["status"] in {"AMBIGUOUS", "INVALID_WITH_EVIDENCE"}]
    if uncertain:
        put("unsupported/ambiguous.list", "".join(f"# line {r['line']}; {r['status']}; {r['reason']}\n{r['raw']}\n" for r in uncertain))
    accounting = audit["source_accounting"]
    audit_md = "# Source audit\n\n" + f"Snapshot: `{metadata['sha256']}`. Full source read as UTF-8.\n\n"
    audit_md += f"{audit['total_lines']} lines; {audit['blank_lines']} blank; {audit['comment_lines']} comments; {len(records)} active rule declarations; {len(audit['non_rule_config'])} non-rule configuration lines.\n\n"
    audit_md += "Sections: " + ", ".join(f"[{s['name']}] (line {s['line']})" for s in audit["sections"]) + ".\n\n"
    audit_md += "| Rule type | Count |\n|---|---:|\n" + "".join(f"| {k} | {v} |\n" for k, v in audit["rule_type_counts"].items())
    audit_md += "\n| Policy | Count |\n|---|---:|\n" + "".join(f"| {k} | {v} |\n" for k, v in audit["policy_counts"].items())
    audit_md += f"\nExact duplicates: {len(duplicates)}; same matcher / multiple policies: {len(conflicts)}. INFORMATIONAL_ONLY. No semantic redundancy analysis or removal.\n\n"
    audit_md += f"Policyless: {len(audit['policyless_rules'])}; invalid: {len(audit['invalid_lines'])}; unsupported: {len(unsupported)}; ambiguous: {accounting['ambiguous']}; no-resolve: {audit['no_resolve_count']}.\n\n"
    audit_md += "PRESERVE SOURCE ORDER. Per-policy projection preserves every occurrence and relative order. It cannot in general preserve interleaved cross-policy priority; canonical/ordered.json is authoritative for global order. External contents are unknown, and overlaps inside them have NOT been audited.\n\n"
    audit_md += "Comment text is preserved only in the frozen source; generated comments describe provenance and terminal handling. No matcher domain/IP rewrites are performed. Known proxy-group/generator settings are recorded as non-rule configuration, not emitted.\n\n"
    audit_md += "SOURCE_ACCOUNTING: " + str(len(records)) + " = " + " + ".join(str(accounting[s.lower()]) for s in STATUSES) + " (generated + unsupported + ambiguous + external_dependency + invalid_with_evidence).\n"
    put("artifacts/source_audit.md", audit_md)
    put("artifacts/compatibility_report.md", """# Compatibility report

| Original syntax | Mihomo classical | Shadowrocket RULE-SET | Conversion / reason |
|---|---|---|---|
| `ruleset=POLICY,https://...` | Cannot nest RULE-SET in classical payload | Nested dependency portability not assumed | External dependency only; URL, policy and order retained; no downloads |
| `ruleset=DIRECT,[]GEOIP,CN` | GEOIP parser supported | Typed GEOIP syntax emitted; on-device import not verified | `GEOIP,CN`; CN matcher retained; requires client's GEOIP database |
| `ruleset=Others,[]FINAL` | MATCH forbidden in classical payload; FINAL not a parser type | Keep terminal action in parent config | Retained in unsupported files and ordered canonical truth; parent `MATCH,<Others policy>` / `FINAL,<Others policy>` only |

Evidence: [subconverter inline syntax](https://github.com/tindy2013/subconverter/blob/master/README-cn.md#自定义规则集), [Mihomo classical parser](https://github.com/MetaCubeX/mihomo/blob/Meta/rules/provider/classical_strategy.go), [Mihomo rule parser](https://github.com/MetaCubeX/mihomo/blob/Meta/rules/parser.go).

Shadowrocket is proprietary: no on-device runtime was available. Its output is a typed rule list, not a DOMAIN-SET. Runtime equivalence across clients and their GEOIP database versions is not claimed. External files' syntax and licenses are unverified because they were not fetched.

The generator accepts only conservative simple DOMAIN, DOMAIN-SUFFIX, DOMAIN-KEYWORD, IP-CIDR, IP-CIDR6 and two-letter GEOIP syntax. Other future syntax is retained with a reason, not approximated. Original no-resolve is preserved; none is added. CIDRs are validated with strict=False but never rewritten. New unknown options are quarantined. FINAL/MATCH remain terminal parent instructions.
""")
    table = "| File | Format | Rules | Purpose |\n|---|---|---:|---|\n"
    for path, contents in list(files.items()):
        if path.startswith(("canonical/", "mihomo/", "shadowrocket/", "unsupported/")) and path.endswith((".list", ".yaml")):
            count = sum(bool(l) and not l.startswith("#") for l in contents.splitlines()) if path.endswith(".list") else len(contents.splitlines()) - 1
            table += f"| [{path}]({path}) | {'YAML classical' if path.endswith('.yaml') else 'typed text'} | {count} | {'Manual handling; do not subscribe' if 'unsupported' in path or 'unclassified' in path else 'Policy projection'} |\n"
    mihomo = "rule-providers:\n"
    for policy, name in mapping.items():
        mihomo += f"  legacy-{name}:\n    type: http\n    behavior: classical\n    format: yaml\n    url: {raw_base}/mihomo/{name}.yaml\n    path: ./ruleset/legacy-{name}.yaml\n    interval: 86400\n"
    mihomo += "rules:\n"
    for policy, name in mapping.items():
        action = policy if policy in {"DIRECT", "REJECT"} else f"<YOUR_POLICY_FOR_{policy}>"
        mihomo += f"  - RULE-SET,legacy-{name},{action}\n"
    shadow = "\n".join(f"RULE-SET,{raw_base}/shadowrocket/{name}.list,{policy if policy in {'DIRECT', 'REJECT'} else '<YOUR_POLICY_FOR_' + policy + '>'}" for policy, name in mapping.items())
    js("artifacts/generated_counts.json", {policy: {"canonical": len(rs), "mihomo": len(rs), "shadowrocket": len(rs)} for policy, rs in groups.items()})
    put("README.md", f"""# Rule Sets

保留源顺序的规则数据仓库；不提供节点、订阅、代理组、DNS、TUN 或完整客户端配置。

## Upstream

[{URL}]({URL})

Commit: `{metadata['commit']}`

SHA-256: `{metadata['sha256']}`

**实际来源是 subconverter 模板：20 个远程依赖、1 条 GEOIP、1 条 FINAL，不是域名规则大全。** 不展开远程依赖，不制造空 proxy/reject 文件；`Proxies` 也不会擅自映射为 `PROXY`。

## Generated Files

{table}

`canonical/ordered.json` 是包含原策略、原行号与全局顺序的唯一 canonical 真源；`.list` 与两个客户端目录是生成的投影。请勿手工编辑生成文件。[完整逐行账本](artifacts/source_accounting.json)覆盖每个有效声明。

## Mihomo Usage

发布后使用下列规则片段；`<GITHUB_RAW_BASE>` 是尚未发布时的明确占位符。可用 `python scripts/update_rules.py --offline --raw-base https://raw.githubusercontent.com/OWNER/REPO/main` 写入最终地址。

```yaml
{mihomo.rstrip()}
```

这个片段只加载本地实际存在的规则，**不能替代整个上游分流**。完整上游顺序是 [external_dependencies.json](artifacts/external_dependencies.json) 中的 20 个引用（按行号），然后第 60 行 GEOIP，再第 61 行 FINAL。只有在原有 20 个依赖已按原顺序接入时，才能把上面的调用放在它们后面；最后用 `MATCH,<YOUR_POLICY_FOR_Others>` 保留原兜底。占位符需替换为你现有策略，本仓库不创建代理组。

## Shadowrocket Usage

```text
{shadow}
```

同样保留原先 20 个依赖在前；最后保留 `FINAL,<YOUR_POLICY_FOR_Others>`。文件保留 GEOIP 类型，未转换为 DOMAIN-SET。没有 iOS 实机导入测试；具体兼容边界见 [报告](artifacts/compatibility_report.md)。

## Statistics

有效声明 {len(records)}；本地生成 {accounting['generated']}；外部依赖 {accounting['external_dependency']}；unsupported {accounting['unsupported']}；ambiguous {accounting['ambiguous']}；invalid {accounting['invalid_with_evidence']}。两客户端各输出相同的本地匹配器，不重复计算 SOURCE_ACCOUNTING。

Exact duplicates {len(duplicates)}，删除 0；semantic dedup 禁用；same matcher multiple policy {len(conflicts)}，仅观察，无冲突消解。完整类型/策略计数见 [审计](artifacts/source_audit.md)。

## Order and normalization

PRESERVE SOURCE ORDER / NO SEMANTIC LOSS / NO SILENT DROP。重复项全部保留，不排序、不覆盖合并，不改域名/IP 匹配范围。只移除 [] 包装和目标策略，统一 rule type 与字段边界空格，生成 UTF-8 / LF / 无 BOM。冻结文件保留原字节。各策略内部保序，但按策略合并调用可能改变跨策略优先顺序，因此全局顺序以 ordered.json 为准。

## Update

```sh
python -m pip install -r requirements.txt
python scripts/update_rules.py
python -m unittest discover -s tests -v
```

默认更新先固定 GitHub commit，再下载该 commit 的原文件、扫描许可证、生成并验证。`--offline` 从冻结快照重建；`--audit-only` 仅生成审计。相同 commit / 内容不刷新 fetched_at，重复生成字节一致。初始 `upstream/4.ini` 永不覆盖，后续变化保存到 `upstream/snapshots/<sha256>/4.ini`；metadata 指向当前快照。未知语法留存隔离，必须审阅报告后发布。上游新许可证需人工审阅，脚本不会替你判定再分发授权。

自动化检查在 GitHub Actions 中运行，定时检查通过 PR 提交更新，不自动合并。仓库需允许 Actions 创建 PR；也可手动运行以上命令。发布权限与最终策略由仓库所有者控制。

## Attribution

规则与原始配置来自 Ghou133/Ghou133.github.io，并非本项目原创。[UPSTREAM.md](UPSTREAM.md) 记录来源与许可范围。当前完整上游树未找到 LICENSE/LICENCE/COPYING 文件；规则数据许可证未声明，未擅自赋予 MIT。远程依赖归各自作者，本仓库只保存引用。冻结原始文件中的历史教程、装饰与非规则设置只作来源证据，不出现在规则输出中。
""")
    put("UPSTREAM.md", f"# Upstream and attribution\n\nRepository: https://github.com/{REPOSITORY}\n\nBranch: {BRANCH}\n\nOriginal: {URL}\n\nPinned: {metadata['pinned_url']}\n\nFetched at: {metadata['fetched_at']}\n\nLicense scan: {json.dumps(metadata['license'], ensure_ascii=False)}\n\nNo license is assigned to upstream rule data or archived text. Absence of a license file does not establish redistribution permission. Generated transformations retain upstream attribution; external contents are not copied. Project scripts/tests have no separate license grant at present.\n")
    return files


def validate(files):
    import yaml
    audit = json.loads(files["artifacts/source_accounting.json"])
    totals, records = audit["totals"], audit["records"]
    assert totals["input_valid_rules"] == sum(totals[s.lower()] for s in STATUSES)
    assert len({r["line"] for r in records}) == len(records)
    for policy, name in json.loads(files["artifacts/policy_mapping.json"]).items():
        expected = [r["matcher"] for r in records if r["status"] == "GENERATED" and r["policy"] == policy]
        assert files[f"canonical/{name}.list"].splitlines() == expected
        assert files[f"shadowrocket/{name}.list"].splitlines() == expected
        payload = yaml.safe_load(files[f"mihomo/{name}.yaml"])["payload"]
        assert isinstance(payload, list) and payload == expected
        for rule in expected:
            assert normalize(rule)[1] == "GENERATED"
    for value in files.values():
        assert value.endswith("\n") and "\r" not in value and not value.startswith("\ufeff")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--raw-base")
    parser.add_argument("--refresh-vendored", action="store_true", help="Explicitly refresh locally maintained third-party snapshots")
    args = parser.parse_args()
    metadata = json.loads((ROOT / "upstream/metadata.json").read_text("utf-8")) if args.offline else snapshot(ROOT)
    source = (ROOT / metadata["snapshot"]).read_bytes()
    if hashlib.sha256(source).hexdigest() != metadata["sha256"]:
        raise ValueError("Frozen snapshot checksum mismatch")
    config_path = ROOT / "project.json"
    config = json.loads(config_path.read_text("utf-8")) if config_path.exists() else {}
    if args.raw_base:
        if not re.fullmatch(r"https://raw\.githubusercontent\.com/[\w.-]+/[\w.-]+/[\w./-]+", args.raw_base):
            raise ValueError("Expected public GitHub Raw base URL without credentials/query")
        config["raw_base"] = args.raw_base.rstrip("/")
    files = build(source, metadata, config.get("raw_base", "<GITHUB_RAW_BASE>"))
    validate(files)
    if args.audit_only:
        for name in ("artifacts/source_audit.json", "artifacts/source_audit.md"):
            write(ROOT / name, files[name])
        print(files["artifacts/source_audit.md"])
        return
    from dependencies import extend_project, validate_project
    if args.offline and args.refresh_vendored:
        raise ValueError("--refresh-vendored requires network access")
    files = extend_project(ROOT, source, metadata, files, config.get("raw_base", "<GITHUB_RAW_BASE>"), offline=args.offline, refresh_vendored=args.refresh_vendored)
    validate_project(files)
    manifest = ROOT / "artifacts/generated_manifest.json"
    previous = json.loads(manifest.read_text("utf-8")) if manifest.exists() else []
    for name in previous:
        if name not in files:
            target = (ROOT / name).resolve()
            if not target.is_relative_to(ROOT.resolve()) or target.suffix not in {".json", ".md", ".yaml", ".list"}:
                raise ValueError("Unsafe generated manifest entry")
            target.unlink(missing_ok=True)
    for name, content in files.items():
        write(ROOT / name, content)
    write(manifest, json_text(list(files)))
    if config:
        write(config_path, json_text(config))
    print(json_text(json.loads(files["artifacts/effective_source_accounting.json"])["totals"]))


if __name__ == "__main__":
    main()
