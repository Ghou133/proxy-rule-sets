import hashlib
import ipaddress
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import update_rules as u
import dependencies as d
import vendor_rules as v


def read_json(name):
    return json.loads((ROOT / name).read_text("utf-8"))


class RuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = read_json("upstream/metadata.json")
        cls.source = (ROOT / cls.metadata["snapshot"]).read_bytes()
        cls.ordered = read_json("canonical/ordered.json")
        cls.records = cls.ordered["records"]
        cls.files = {name: (ROOT / name).read_text("utf-8") for name in read_json("artifacts/generated_manifest.json")}

    def test_all_generated_validation(self):
        d.validate_project(self.files)

    def test_all_snapshots_have_matching_hashes(self):
        for metadata in [self.metadata] + read_json("upstream/owned_metadata.json"):
            data = (ROOT / metadata["snapshot"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), metadata["sha256"])
            self.assertEqual(metadata["commit"], self.metadata["commit"])

    def test_original_and_expanded_accounting(self):
        for path, record_key in (("artifacts/source_accounting.json", "records"), ("artifacts/expanded_source_accounting.json", "local_records")):
            report = read_json(path)
            totals = report["totals"]
            self.assertEqual(totals["input_valid_rules"], sum(totals[s.lower()] for s in u.STATUSES))
            self.assertEqual(totals["unexplained_loss"], 0)
            for record in report[record_key]:
                self.assertIn(record["status"], u.STATUSES)
                self.assertTrue(record["reason"])

    def test_every_original_declaration_and_owned_line_accounted(self):
        parents = u.parse(self.source)[1]
        original = read_json("artifacts/source_accounting.json")["records"]
        self.assertEqual([(r["line"], r["raw"]) for r in parents], [(r["line"], r["raw"]) for r in original])
        for m in read_json("upstream/owned_metadata.json"):
            expected = d.typed_lines((ROOT / m["snapshot"]).read_bytes())
            actual = [(r["line"], r["raw"]) for r in self.records if r["parent_line"] == m["parent_line"]]
            self.assertEqual(expected, actual)

    def test_canonical_parse_and_provider_policy_absence(self):
        for r in self.records:
            if r["status"] == "GENERATED":
                normalized, status, _ = u.normalize(r["matcher"])
                self.assertEqual(status, "GENERATED")
                self.assertEqual(normalized, r["matcher"])
                fields = normalized.split(",")
                self.assertIn(len(fields), (2, 3))
                if len(fields) == 3:
                    self.assertEqual(fields[2], "no-resolve")
        for path in ROOT.glob("canonical/*.list"):
            for line in path.read_text("utf-8").splitlines():
                if line and not line.startswith("#"):
                    self.assertIn(u.normalize(line)[1], u.STATUSES)

    def test_domains_and_cidrs(self):
        for r in self.records:
            fields = r["matcher"].split(",")
            if r["type"].startswith("DOMAIN"):
                self.assertFalse(any(c.isspace() for c in fields[1]))
                self.assertFalse(any(c in fields[1] for c in "/\\:"))
            if r["type"] in {"IP-CIDR", "IP-CIDR6"}:
                ipaddress.ip_network(fields[1], strict=False)

    def test_duplicate_occurrences_and_source_order_preserved(self):
        for policy, name in read_json("artifacts/policy_mapping.json").items():
            expected = [r["matcher"] for r in self.records if r["policy"] == policy and r["status"] == "GENERATED"]
            self.assertEqual((ROOT / f"canonical/{name}.list").read_text("utf-8").splitlines(), expected)
        report = read_json("artifacts/dedup_report.json")
        by_id = {r["id"]: r for r in self.records}
        for duplicate in report["preserved_duplicates"]:
            self.assertEqual(by_id[duplicate["occurrence"]]["matcher"], by_id[duplicate["first_occurrence"]]["matcher"])
        self.assertEqual(report["exact_duplicates_removed"], 0)
        self.assertEqual(report["semantic_duplicates_removed"], 0)

    def test_global_segment_sequence_and_payload(self):
        by_id = {r["id"]: r for r in self.records}
        last = 0
        for step in self.ordered["sequence"]:
            self.assertGreater(step["parent_line"], last)
            last = step["parent_line"]
            if step["kind"] == "external":
                continue
            for target, suffix in (("mihomo", "yaml"), ("shadowrocket", "list")):
                expected = [by_id[i]["matcher"] for i in step["record_ids"] if by_id[i]["targets"][target] == "GENERATED"]
                path = ROOT / f"{target}/segments/{step['segment']}.{suffix}"
                if expected:
                    content = path.read_text("utf-8")
                    actual = yaml.safe_load(content)["payload"] if suffix == "yaml" else content.splitlines()
                    self.assertEqual(actual, expected)
                else:
                    self.assertFalse(path.exists())
        example = yaml.safe_load(self.files["examples/mihomo-rules.yaml"])
        actual = [int(r.split(",")[1].removeprefix("source-")) for r in example["rules"] if r.startswith("RULE-SET,")]
        expected = [s["parent_line"] for s in self.ordered["sequence"] if s["kind"] == "external" or any(by_id[i]["targets"]["mihomo"] == "GENERATED" for i in s["record_ids"])]
        self.assertEqual(actual, expected)
        self.assertTrue(example["rules"][-1].startswith("MATCH,"))

    def test_target_unsupported_counts(self):
        for target in ("mihomo", "shadowrocket"):
            expected = [r["matcher"] for r in self.records if r["targets"][target] != "GENERATED"]
            path = ROOT / f"unsupported/{target}.list"
            actual = [l for l in path.read_text("utf-8").splitlines() if l and not l.startswith("#")]
            self.assertEqual(actual, expected)
            total = read_json("artifacts/expanded_source_accounting.json")["per_target"][target]
            self.assertEqual(sum(total.values()), len(self.records))

    def test_generated_inventory_counts(self):
        for item in read_json("artifacts/generated_counts.json"):
            path = ROOT / item["file"]
            text = path.read_text("utf-8")
            if path.suffix == ".yaml":
                rules = yaml.safe_load(text)["payload"]
                self.assertIsInstance(rules, list)
            else:
                rules = [l for l in text.splitlines() if l and not l.startswith("#")]
            self.assertEqual(len(rules), item["rules"])

    def test_utf8_lf_no_bom_final_newline(self):
        for name in read_json("artifacts/generated_manifest.json"):
            data = (ROOT / name).read_bytes()
            data.decode("utf-8")
            self.assertNotIn(b"\r", data, name)
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"), name)
            self.assertTrue(data.endswith(b"\n"), name)

    def test_external_choice_never_substitutes_different_yaml(self):
        for ref in read_json("artifacts/external_dependencies.json"):
            self.assertFalse(ref["materialized"])
            if ref["format"] == "yaml":
                self.assertTrue(ref["ordered_equal"])
                self.assertEqual(ref["selected_url"], ref["yaml_candidate_url"])
            else:
                self.assertEqual(ref["selected_url"], ref["url"])

    def test_offline_generation_is_byte_deterministic(self):
        raw = read_json("project.json")["raw_base"] if (ROOT / "project.json").exists() else "<GITHUB_RAW_BASE>"
        first = d.extend_project(ROOT, self.source, self.metadata, u.build(self.source, self.metadata, raw), raw, offline=True)
        second = d.extend_project(ROOT, self.source, self.metadata, u.build(self.source, self.metadata, raw), raw, offline=True)
        self.assertEqual(first, second)
        self.assertEqual(first, self.files)

    def test_conservative_normalization_fixtures(self):
        cases = {
            " domain-suffix , Example.COM ": "DOMAIN-SUFFIX,Example.COM",
            "IP-CIDR,192.168.1.1/24,no-resolve": "IP-CIDR,192.168.1.1/24,no-resolve",
            "IP-CIDR6,2001:db8::1/64,no-resolve": "IP-CIDR6,2001:db8::1/64,no-resolve",
            "PROCESS-NAME, Razer Synapse Service.exe": "PROCESS-NAME,Razer Synapse Service.exe",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(u.normalize(raw)[:2], (expected, "GENERATED"))
        for raw in ("DOMAIN,https://example.com", "DOMAIN,example.com/path", "DOMAIN,exam ple.com", "IP-CIDR,999.1.1.1/24"):
            self.assertEqual(u.normalize(raw)[1], "INVALID_WITH_EVIDENCE")
        self.assertEqual(u.normalize("DOMAIN,example.com,PROXY")[1], "AMBIGUOUS")
        self.assertEqual(u.normalize("DOMAIN-SUFFIX,*.example.com")[1], "AMBIGUOUS")
        raw = "AND,((DOMAIN,a.com),(DST-PORT,443))"
        self.assertEqual(u.normalize(raw)[0], raw)
        self.assertEqual(u.normalize(raw)[1], "UNSUPPORTED")

    def test_fixture_duplicates_conflicts_unknowns_and_policyless(self):
        source = b"[custom]\nruleset=DIRECT,[]DOMAIN,a.com\nruleset=Proxies,[]DOMAIN,a.com\nruleset=DIRECT,[]DOMAIN,a.com\nruleset=,[]DOMAIN,b.com\nruleset=DIRECT,[]IP-CIDR,invalid\nNEW-SYNTAX,keep-me\n"
        audit, records, duplicates, conflicts = u.audit_source(source)
        self.assertEqual(len(records), 6)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual([r["line"] for r in records], list(range(2, 8)))
        self.assertEqual(records[3]["status"], "AMBIGUOUS")
        self.assertEqual(records[4]["status"], "INVALID_WITH_EVIDENCE")
        self.assertEqual(records[5]["matcher"], "NEW-SYNTAX,keep-me")

    def test_snapshot_updates_never_overwrite_initial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = b"[custom]\nruleset=DIRECT,[]GEOIP,CN\n"
            second = b"[custom]\nruleset=DIRECT,[]DOMAIN,a.com\n"
            with patch.object(u, "fetch", side_effect=[b'{"sha":"a"}', first, b'{"tree":[]}']):
                one = u.snapshot(root)
            with patch.object(u, "fetch", side_effect=[b'{"sha":"b"}', second, b'{"tree":[]}']):
                two = u.snapshot(root)
            self.assertEqual((root / "upstream/4.ini").read_bytes(), first)
            self.assertEqual((root / two["snapshot"]).read_bytes(), second)
            with patch.object(u, "fetch", side_effect=[b'{"sha":"b"}', second, b'{"tree":[]}']):
                again = u.snapshot(root)
            self.assertEqual(two, again)
            self.assertNotEqual(one["snapshot"], two["snapshot"])

    def test_vendor_full_source_and_license_accounting(self):
        for spec in read_json("upstream/vendor_metadata.json"):
            data = (ROOT / spec["snapshot"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), spec["sha256"])
            license_bytes = (ROOT / spec["license_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(license_bytes).hexdigest(), spec["license_sha256"])
            path = f"artifacts/vendor/{spec['namespace']}/{spec['name']}.json"
            ledger = read_json(path)
            self.assertEqual(d.typed_lines(data), [(r["line"], r["raw"]) for r in ledger["records"]])
            self.assertEqual(ledger["totals"]["input_valid_rules"], sum(ledger["totals"][s.lower()] for s in u.STATUSES))

    def test_vendor_projections_keep_duplicates_and_attribution(self):
        v.validate_vendor(self.files)
        for output in read_json("artifacts/vendor_outputs.json"):
            source = output["source"]
            for name in [output["canonical"], *(o["file"] for o in output["outputs"].values())]:
                text = self.files[name]
                self.assertIn(source["url"], text)
                self.assertIn(source["repository"], text)
                self.assertIn(source["license"], text)
            ledger = read_json(output["accounting"])
            for target in ("mihomo", "shadowrocket"):
                expected = [r["matcher"] for r in ledger["records"] if r["targets"][target] != "GENERATED"]
                name = f"unsupported/vendor/{target}/{source['namespace']}/{source['name']}.list"
                self.assertEqual(v.noncomments(self.files.get(name, "")), expected)

    def test_effective_accounting_and_local_usage_urls(self):
        report = read_json("artifacts/effective_source_accounting.json")
        for totals in [report["totals"], *report["per_target"].values()]:
            self.assertEqual(totals["input_valid_rules"], sum(totals[s.lower()] for s in u.STATUSES))
        example = yaml.safe_load(self.files["examples/mihomo-rules.yaml"])
        for item in read_json("artifacts/vendor_outputs.json"):
            source = item["source"]
            url = example["rule-providers"][f"source-{source['parent_line']:03d}"]["url"]
            self.assertTrue(url.endswith("/" + item["outputs"]["mihomo"]["file"]))
            self.assertNotEqual(url, source["url"])

    def test_default_vendor_rebuild_never_fetches_original(self):
        with patch.object(v, "fetch", side_effect=AssertionError("Must rebuild frozen vendor data without network")):
            specs = v.prepare(ROOT, read_json("upstream/external_metadata.json"), False, False)
        self.assertEqual(len(specs), len(read_json("upstream/vendor_metadata.json")))


if __name__ == "__main__":
    unittest.main()
