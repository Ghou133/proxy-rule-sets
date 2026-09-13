"""Explicitly authorized local copies of five mismatched third-party rule sources."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

import yaml
from update_rules import STATUSES, fetch, json_text, normalize, write
from dependencies import digest, typed_lines, provider_yaml


LICENSES = {
    "ACL4SSR/ACL4SSR": ("LICENCE", "CC-BY-SA-4.0", "https://creativecommons.org/licenses/by-sa/4.0/"),
    "blackmatrix7/ios_rule_script": ("LICENSE", "GPL-2.0", "https://www.gnu.org/licenses/old-licenses/gpl-2.0.html"),
}


def prepare(root, third, offline, refresh):
    path = root / "upstream/vendor_metadata.json"
    previous = json.loads(path.read_text("utf-8")) if path.exists() else []
    by_url = {r["url"]: r for r in previous}
    # Initial scope is exactly the previously mismatched five references, not all internet dependencies.
    refs = [r for r in third if r["url"] in by_url or (not previous and r["format"] == "text")]
    if previous and len(refs) != len(previous):
        raise ValueError("A locally maintained reference disappeared from 4.ini; review before updating")
    result = []
    for ref in refs:
        if ref["url"] in by_url and not refresh:
            item = by_url[ref["url"]]
        else:
            if offline:
                raise ValueError("Initial vendoring needs one online run")
            repository = ref["repository"]
            filename, license_id, license_url = LICENSES[repository]
            pinned = ref["url"].replace("/master/", "/" + ref["commit"] + "/", 1)
            data = fetch(pinned)
            if digest(data) != ref["original_sha256"]:
                raise ValueError("Vendored source does not match audited source checksum")
            data.decode("utf-8-sig")
            license_bytes = fetch(f"https://raw.githubusercontent.com/{repository}/{ref['commit']}/{filename}")
            namespace = repository.split("/")[0].lower()
            snapshot = f"upstream/vendor/{namespace}/{digest(data)}/{Path(ref['url']).name}"
            license_path = f"upstream/vendor/{namespace}/licenses/{digest(license_bytes)}/{filename}"
            for name, content in ((snapshot, data), (license_path, license_bytes)):
                destination = root / name
                if destination.exists() and destination.read_bytes() != content:
                    raise ValueError("Refusing to overwrite frozen third-party evidence")
                write(destination, content)
            old = by_url.get(ref["url"], {})
            item = {"url": ref["url"], "repository": repository, "branch": "master", "commit": ref["commit"],
                    "sha256": digest(data), "pinned_url": pinned, "snapshot": snapshot,
                    "fetched_at": old.get("fetched_at") if old.get("sha256") == digest(data) else datetime.now(timezone.utc).isoformat(),
                    "license": license_id, "license_url": license_url, "license_path": license_path,
                    "license_sha256": digest(license_bytes), "namespace": namespace,
                    "name": Path(ref["url"]).stem.lower(), "parent_line": ref["parent_line"], "policy": ref["policy"]}
        # Both source bytes and license evidence are required for an offline rebuild.
        for key, hash_key in (("snapshot", "sha256"), ("license_path", "license_sha256")):
            if digest((root / item[key]).read_bytes()) != item[hash_key]:
                raise ValueError("Vendored source/license checksum mismatch")
        result.append(item)
    if not offline:
        write(path, json_text(result))
    return result


def noncomments(text):
    return [l for l in text.splitlines() if l and not l.startswith("#")]


def materialize(root, files, third, raw_base, offline=False, refresh=False):
    specs = prepare(root, third, offline, refresh)
    mirrored = {r["url"] for r in specs}
    remaining = [r for r in third if r["url"] not in mirrored]
    audits, output_specs, local_rows = [], [], []
    inventory = json.loads(files["artifacts/generated_counts.json"])
    example = yaml.safe_load(files["examples/mihomo-rules.yaml"])
    shadow = files["examples/shadowrocket-rules.list"]
    ordered = json.loads(files["canonical/ordered.json"])
    for spec in specs:
        raw = (root / spec["snapshot"]).read_bytes()
        entries = []
        for line, original in typed_lines(raw):
            matcher, status, reason = normalize(original)
            row = {"line": line, "raw": original, "matcher": matcher, "status": status, "reason": reason,
                   "targets": {"mihomo": status, "shadowrocket": "UNSUPPORTED" if matcher.startswith("PROCESS-NAME,") else status}}
            if status == "UNSUPPORTED" and matcher.startswith(("URL-REGEX,", "USER-AGENT,")):
                row["reason"] = "Mihomo does not support this matcher; Shadowrocket provider compatibility unverified. Preserved verbatim, no approximation."
            entries.append(row)
            local_rows.append({**row, "source": spec["url"], "parent_line": spec["parent_line"], "policy": spec["policy"]})
        prefix = f"{spec['namespace']}/{spec['name']}"
        header = (f"# Source repository: https://github.com/{spec['repository']}\n"
                  f"# Original file: {spec['url']}\n# Pinned commit: {spec['commit']}\n"
                  f"# License: {spec['license']} {spec['license_url']}\n"
                  f"# Modified {spec['fetched_at'][:10]} by Rule Sets Maintainer: whitespace/format only; source order and duplicates retained.\n"
                  "# Unsupported target rules are preserved in unsupported/vendor/; see per-source accounting.\n"
                  "# No warranty. Original source and full license are included under upstream/vendor/.\n")
        # Canonical holds ALL occurrences, including unsupported rules, within the source's license namespace.
        canonical = f"canonical/vendor/{prefix}.list"
        files[canonical] = header + "\n".join(r["matcher"] for r in entries) + "\n"
        ledger_path = f"artifacts/vendor/{prefix}.json"
        files[ledger_path] = json_text({"source": spec, "records": entries,
            "totals": {"input_valid_rules": len(entries), **{s.lower(): sum(r["status"] == s for r in entries) for s in STATUSES}},
            "per_target": {t: {s.lower(): sum(r["targets"][t] == s for r in entries) for s in STATUSES} for t in ("mihomo", "shadowrocket")}})
        files[f"canonical/vendor/{prefix}.metadata.json"] = json_text({"source": spec, "accounting": ledger_path})
        generated = {}
        for target, suffix in (("mihomo", "yaml"), ("shadowrocket", "list")):
            values = [r["matcher"] for r in entries if r["targets"][target] == "GENERATED"]
            name = f"{target}/vendor/{prefix}.{suffix}"
            if values:
                files[name] = header + (provider_yaml(values) if suffix == "yaml" else "\n".join(values) + "\n")
                inventory.append({"file": name, "rules": len(values), "purpose": f"Local maintained copy; {spec['license']}"})
            held = [r for r in entries if r["targets"][target] != "GENERATED"]
            if held:
                files[f"unsupported/vendor/{target}/{prefix}.list"] = header + "".join(f"# source line {r['line']}; {r['reason']}\n{r['matcher']}\n" for r in held)
            generated[target] = {"file": name if values else None, "rules": len(values), "unsupported": len(held)}
        counts = Counter(r["matcher"].split(",", 1)[0] for r in entries)
        audits.append({"source": spec, "input_valid_rules": len(entries), "types": dict(counts), "outputs": generated, "accounting": ledger_path})
        output_specs.append({"source": spec, "canonical": canonical, "accounting": ledger_path, "outputs": generated})
        key = f"source-{spec['parent_line']:03d}"
        example["rule-providers"][key].update(behavior="classical", format="yaml", url=raw_base + "/" + generated["mihomo"]["file"], path=f"./ruleset/{key}.yaml")
        shadow = shadow.replace("RULE-SET," + spec["url"] + ",", "RULE-SET," + raw_base + "/" + generated["shadowrocket"]["file"] + ",")
        for step in ordered["sequence"]:
            if step["parent_line"] == spec["parent_line"]:
                step["dependency"].update(materialized=True, local_canonical=canonical, local_accounting=ledger_path)
    files["examples/mihomo-rules.yaml"] = "# Ordered rules-only fragment; replace policy placeholders. Unsupported rules are retained outside provider payloads.\n" + yaml.safe_dump(example, allow_unicode=True, sort_keys=False, width=200)
    files["examples/shadowrocket-rules.list"] = shadow
    files["canonical/ordered.json"] = json_text(ordered)
    files["artifacts/external_dependencies.json"] = json_text(remaining)
    files["artifacts/generated_counts.json"] = json_text(inventory)
    files["artifacts/vendor_source_audit.json"] = json_text(audits)
    files["artifacts/vendor_outputs.json"] = json_text(output_specs)
    original = json.loads(files["artifacts/source_accounting.json"])
    for row in original["records"]:
        if row.get("url") in mirrored:
            row.update(materialized=True, reason="Explicitly authorized local third-party copy; full leaf accounting in artifacts/vendor/")
    files["artifacts/source_accounting.json"] = json_text(original)
    # Existing own-source and per-vendor ledgers are disjoint; this summary combines counts only.
    base = json.loads(files["artifacts/expanded_source_accounting.json"])
    all_rows = base["local_records"] + local_rows
    totals = {"input_valid_rules": len(all_rows) + len(remaining), **{s.lower(): sum(r["status"] == s for r in all_rows) for s in STATUSES}}
    totals["external_dependency"] += len(remaining)
    targets = {t: {"input_valid_rules": len(all_rows) + len(remaining), **{s.lower(): sum(r["targets"][t] == s for r in all_rows) for s in STATUSES}} for t in ("mihomo", "shadowrocket")}
    for counts in targets.values():
        counts["external_dependency"] += len(remaining)
    files["artifacts/effective_source_accounting.json"] = json_text({"totals": totals, "per_target": targets, "unexplained_loss": 0,
        "scope": "Own leaf records + local vendor leaf records + remaining remote reference units; no container/leaf double count",
        "own_ledger": "artifacts/expanded_source_accounting.json", "vendor_ledgers": [a["accounting"] for a in audits]})
    # Audit duplicate/conflict observations across the effective stream without rewriting any data.
    occurrences = defaultdict(list)
    for r in sorted(all_rows, key=lambda r: (r["parent_line"], r["line"])):
        occurrences[r["matcher"]].append({"file": r.get("source", r.get("file")), "line": r["line"], "parent_line": r["parent_line"], "policy": r["policy"]})
    duplicates, conflicts = [], []
    for matcher, locations in occurrences.items():
        seen = {}
        for loc in locations:
            if loc["policy"] in seen:
                duplicates.append({"matcher": matcher, "first": seen[loc["policy"]], "repeated": loc, "action": "PRESERVED"})
            else:
                seen[loc["policy"]] = loc
        if len(seen) > 1:
            conflicts.append({"matcher": matcher, "locations": locations, "action": "INFORMATIONAL_ONLY"})
    files["artifacts/effective_duplicates.json"] = json_text({"exact_duplicate_count": len(duplicates), "removed": 0, "items": duplicates})
    files["artifacts/effective_conflicts.json"] = json_text({"same_matcher_multiple_policy_count": len(conflicts), "items": conflicts})
    table = "| Source | Canonical | Mihomo | Shadowrocket | License |\n|---|---:|---:|---:|---|\n"
    for audit in audits:
        table += f"| {audit['source']['repository']}/{audit['source']['name']} | {audit['input_valid_rules']} | {audit['outputs']['mihomo']['rules']} | {audit['outputs']['shadowrocket']['rules']} | {audit['source']['license']} |\n"
    report = "# Locally maintained third-party rules\n\n" + table
    report += "\nEvery output file includes original repository/file URLs, pinned commit, license and modification date. All original occurrences remain in canonical/vendor, frozen source and per-source ledgers. Unsupported rules remain in unsupported/vendor. No sorting, deduplication, matcher changes or inferred policies. Separate license namespaces are retained; these copies are not merged into the unlicensed own-policy files.\n\n"
    report += "Default updates rebuild these files from their frozen snapshots. To intentionally synchronize from original upstream, run `python scripts/update_rules.py --refresh-vendored`; this stores new immutable snapshots and regenerates reports. Normal runtime loads this repository's Raw files. Six equivalent third-party YAML references remain remote.\n\n"
    report += "Mihomo cannot implement 7 URL-REGEX and 3 USER-AGENT entries. These are retained, not approximated. Shadowrocket exports conservative verified syntax only: Windows process rules and the 10 unverified regex/agent rules remain in its unsupported ledger. No iOS runtime equivalence is claimed.\n"
    files["artifacts/vendor_source_audit.md"] = report
    files["artifacts/compatibility_report.md"] = report + "\nOriginal YAML comparison evidence remains in third_party_yaml_audit.json. The former text-fallback choices are replaced by local vendor files in the actual usage example. Parent FINAL remains unsupported in provider payloads and is emitted only as parent MATCH/FINAL.\n"
    files["UPSTREAM.md"] += "\n## Local third-party copies\n\n" + table
    for spec in {s["repository"]: s for s in specs}.values():
        files["UPSTREAM.md"] += f"\n- {spec['repository']}: [{spec['license']}]({spec['license_path']}); namespace `*/vendor/{spec['namespace']}/`. Original and converted datasets retain that license; original source and change-generation scripts accompany the files.\n"
    files["UPSTREAM.md"] = files["UPSTREAM.md"].replace("external contents are not copied", "authorized third-party copies are documented below")
    # Replace stale previous-scope narrative, retaining only current statistics and actual usable examples.
    current_table = "| File | Format | Rules | Purpose |\n|---|---|---:|---|\n"
    for i in inventory:
        if "/segments/" not in i["file"]:
            current_table += f"| [{i['file']}]({i['file']}) | {'YAML' if i['file'].endswith('.yaml') else 'typed list'} | {i['rules']} | {i['purpose']} |\n"
    files["README.md"] = f"""# Rule Sets

保留原策略、原顺序、重复项的规则数据仓库。只提供规则与引用片段，不包含节点、订阅、代理组、DNS 或完整主配置。

## Upstream

来源：[Ghou133/4.ini](https://raw.githubusercontent.com/Ghou133/Ghou133.github.io/refs/heads/master/archives/4.ini)。原始 commit、SHA-256、下载时间见 [metadata](upstream/metadata.json)；9 个自有引用共 280 条规则均已冻结并转换。

5 个第三方原文本与同名 YAML 不一致，因此本仓库维护其完整规范版本；6 个核对一致的第三方 YAML 继续远程引用。每个本地第三方文件都注明原仓库和许可证。默认使用冻结版本，需要同步时显式更新。

## Generated Files

{current_table}

`canonical/ordered.json` 记录全局调用顺序与每个来源的 canonical 文件。自有策略文件与第三方许可目录保持分离；引用示例按源位置调用，不能把所有 DIRECT 聚合提前。segments 与聚合文件是相同数据的不同投影，统计不重复相加。

## Mihomo Usage

[完整保序片段](examples/mihomo-rules.yaml)包含 rule-providers 和 rules，所有本地文件都使用本仓库地址。发布前 `<GITHUB_RAW_BASE>` 是待替换占位符；发布脚本会填入实际地址。

```yaml
rule-providers:
  legacy-download:
    type: http
    behavior: classical
    format: yaml
    url: {raw_base}/mihomo/vendor/acl4ssr/download.yaml
    path: ./ruleset/legacy-download.yaml
    interval: 86400
rules:
  - RULE-SET,legacy-download,DIRECT
```

该文件保留 13 条进程规则及 2 条域名规则，不采用只有 2 条的第三方同名 YAML。7 条 URL-REGEX 在 unsupported/vendor 中保留；Mihomo 本身不支持，不能通过另建文件解决。完整示例的 `<YOUR_POLICY_FOR_...>` 替换为你现有策略，未创建任何代理组。

## Shadowrocket Usage

```text
RULE-SET,{raw_base}/shadowrocket/vendor/acl4ssr/unban.list,DIRECT
```

[完整保序片段](examples/shadowrocket-rules.list)。保留类型，不是 DOMAIN-SET。Windows 进程规则及未验证的 URL-REGEX/USER-AGENT 规则单独留存；没有 iOS 实机验证。

## Statistics

完整有效账本：**{totals['input_valid_rules']} = {' + '.join(str(totals[s.lower()]) for s in STATUSES)}**（generated + unsupported + ambiguous + external_dependency + invalid_with_evidence）。Mihomo 本地生成 {targets['mihomo']['generated']} 条；Shadowrocket 本地生成 {targets['shadowrocket']['generated']} 条。Unexplained loss = 0。

有效数据流 exact duplicate occurrences {len(duplicates)}，全部保留，删除 0；同 matcher 多 policy {len(conflicts)}，仅观察、不消解。语义去重禁用。见 [总账本](artifacts/effective_source_accounting.json)、[重复报告](artifacts/effective_duplicates.json)、[多策略报告](artifacts/effective_conflicts.json)。

## Update

```sh
python -m pip install -r requirements.txt
python scripts/update_rules.py
python -m unittest discover -s tests -v
```

通常更新自有上游并从冻结第三方快照重建。需要主动同步本地维护的第三方文件时：`python scripts/update_rules.py --refresh-vendored`。离线复现：`python scripts/update_rules.py --offline`。原始快照永不覆盖；相同输入重复运行不产生 Git 差异。GitHub Actions 检查并提出每周更新 PR，不自动合并。

仅做类型、字段边界空格、UTF-8/LF 格式转换；不改 matcher、no-resolve、进程名内部空格，不排序、不删重复。未知语法保留并记账。完整兼容范围见 [兼容报告](artifacts/compatibility_report.md)。

## Clash Verge Rev 扩展

[有落地 / 无落地全局扩展脚本](extensions/README.md)会接入本仓库保序规则，并把 ChatGPT、Claude、Gemini 统一到一个 AI 策略组。扩展脚本与规则数据独立存放，公开版本不含节点凭据。

[Shadowrocket 手机配置](clients/shadowrocket/README.md)提供有落地 / 无落地两版，使用维护中的远程 AI、LAN、国内规则，无广告过滤。私人连接参数不在公开仓库中。

## Attribution

自有来源 Ghou133/Ghou133.github.io 未声明许可证，不擅自赋予 MIT。ACL4SSR 副本及格式转换保留 CC BY-SA 4.0；blackmatrix7 副本及格式转换保留 GPLv2，分别放在独立目录。完整许可证、原始文本、来源与修改说明随仓库提供，见 [UPSTREAM.md](UPSTREAM.md)。这些第三方数据不是本仓库原创。
"""
    validate_vendor(files)
    return files


def validate_vendor(files):
    for item in json.loads(files["artifacts/vendor_outputs.json"]):
        ledger = json.loads(files[item["accounting"]])
        records = ledger["records"]
        assert noncomments(files[item["canonical"]]) == [r["matcher"] for r in records]
        for target in ("mihomo", "shadowrocket"):
            expected = [r["matcher"] for r in records if r["targets"][target] == "GENERATED"]
            path = item["outputs"][target]["file"]
            actual = yaml.safe_load(files[path])["payload"] if target == "mihomo" else noncomments(files[path])
            assert actual == expected
            assert len(actual) == item["outputs"][target]["rules"]
        assert ledger["totals"]["input_valid_rules"] == sum(ledger["totals"][s.lower()] for s in STATUSES)
    effective = json.loads(files["artifacts/effective_source_accounting.json"])
    for totals in [effective["totals"], *effective["per_target"].values()]:
        assert totals["input_valid_rules"] == sum(totals[s.lower()] for s in STATUSES)
