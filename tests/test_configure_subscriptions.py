import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from configure_subscriptions import ConfigurationError, build, extract_dns_policies, extract_hosts, load_yaml, write_private


def template(**options):
    return "// fixture\nconst OPTIONS = " + json.dumps({"multiSubscription": True, **options}) + ";\nconst MANIFEST = {};\nfunction main(x) { return x; }\n"


def options(script):
    return json.JSONDecoder().raw_decode(script.split("const OPTIONS = ", 1)[1])[0]


def source(*servers, dns=None, **extra):
    return {"proxies": [{"name": "fixture " + str(i), "type": "ss", "server": server} for i, server in enumerate(servers)], "dns": dns or {}, **extra}


class ConfigureSubscriptionsTests(unittest.TestCase):
    def setUp(self):
        self.entry = {"proxy-providers": {
            "airport-1": {"type": "http", "url": "https://fixture.invalid/a?token=PRIVATE_FIXTURE", "header": {"User-Agent": ["fixture-client"]}, "override": {"additional-prefix": "[A] "}},
            "airport-2": {"type": "http", "url": "https://fixture.invalid/b", "override": {"additional-prefix": "[B] "}},
        }}

    def test_exact_comma_suffix_and_node_only_policy_extraction(self):
        result, domains = extract_dns_policies(source("one.example", "two.example", "a.nodes.example", "198.51.100.1", dns={
            "nameserver-policy": {"one.example, two.example, unused.example": ["1.1.1.1", "8.8.8.8"], "+.nodes.example": "9.9.9.9", "other.example": "223.5.5.5"},
            "proxy-server-nameserver-policy": {"one.example": ["1.1.1.1", "8.8.8.8"]},
            "nameserver": ["192.0.2.99"],
        }))
        self.assertEqual(list(result), ["one.example", "two.example", "+.nodes.example"])
        self.assertEqual(result["one.example"], ["1.1.1.1", "8.8.8.8"])
        self.assertEqual(domains, ["one.example", "two.example", "a.nodes.example"])

    def test_two_provider_defaults_preserve_options_and_providers(self):
        original = copy.deepcopy(self.entry)
        landing = {"type": "ss", "server": "exit.fixture.invalid", "password": "LOCAL_FIXTURE"}
        script = build(self.entry, template(landing=True, landingProxy=landing), {
            "airport-1": source("one.example", dns={"proxy-server-nameserver": ["1.1.1.1"]}),
            "airport-2": source("two.example", dns={"proxy-server-nameserver": "8.8.8.8", "nameserver": ["9.9.9.9"]}),
        })
        result = options(script)
        self.assertEqual(result["subscriptionDnsPolicies"], {"airport-1": {"one.example": ["1.1.1.1"]}, "airport-2": {"two.example": "8.8.8.8"}})
        self.assertEqual(result["landingProxy"], landing)
        self.assertEqual(result["subscriptionProviders"], original["proxy-providers"])
        self.assertEqual(self.entry, original)
        self.assertTrue(script.endswith("function main(x) { return x; }\n"))

    def test_generic_nameserver_does_not_become_node_policy(self):
        result, _ = extract_dns_policies(source("one.example", dns={"nameserver": ["8.8.8.8"]}))
        self.assertEqual(result, {})

    def test_explicit_policy_wins_over_node_resolver_default(self):
        result, _ = extract_dns_policies(source("one.example", "two.example", dns={"nameserver-policy": {"one.example": "1.1.1.1"}, "proxy-server-nameserver": ["8.8.8.8"]}))
        self.assertEqual(result, {"one.example": "1.1.1.1", "two.example": ["8.8.8.8"]})

    def test_conflicting_explicit_and_cross_provider_policies_fail(self):
        with self.assertRaisesRegex(ConfigurationError, "conflicting explicit"):
            extract_dns_policies(source("one.example", dns={"nameserver-policy": {"one.example": "1.1.1.1"}, "proxy-server-nameserver-policy": {"one.example": "8.8.8.8"}}))
        with self.assertRaisesRegex(ConfigurationError, "conflicting DNS"):
            build(self.entry, template(), {
                "airport-1": source("one.example", dns={"nameserver-policy": {"+.example": "1.1.1.1"}}),
                "airport-2": source("one.example", dns={"proxy-server-nameserver": ["8.8.8.8"]}),
            })

    def test_unsupported_selector_hosts_and_recursive_provider_fail(self):
        for dns in ({"nameserver-policy": {"geosite:cn": "1.1.1.1"}}, {"nameserver-policy": {"rule-set:private": "1.1.1.1"}}):
            with self.assertRaisesRegex(ConfigurationError, "coverage cannot be proven"):
                extract_dns_policies(source("one.example", dns=dns))
        fixture = source("one.example", hosts={"one.example": "198.51.100.1"})
        self.assertEqual(extract_hosts(fixture, *extract_dns_policies(fixture)), {"one.example": "198.51.100.1"})
        fixture = source("one.example", dns={"proxy-server-nameserver": ["https://dns.example/dns-query"]}, hosts={"dns.example": "198.51.100.1"})
        self.assertEqual(extract_hosts(fixture, *extract_dns_policies(fixture)), {"dns.example": "198.51.100.1"})
        with self.assertRaisesRegex(ConfigurationError, "recursive providers"):
            extract_dns_policies({"proxy-providers": {"nested": {"type": "http"}}})

    def test_hosts_retain_only_bootstrap_dependencies_and_recursive_aliases(self):
        fixture = source("one.example", dns={"nameserver-policy": {"one.example": ["https://dns.example/dns-query", "backup.example:53"]}}, hosts={
            "unrelated.example": "198.51.100.9", "DNS.Example.": "alias.example", "alias.example": ["198.51.100.1", "2001:db8::1"],
            "backup.example": "198.51.100.2", "one.example": "198.51.100.3",
        })
        result = extract_hosts(fixture, *extract_dns_policies(fixture))
        self.assertEqual(list(result), ["DNS.Example.", "alias.example", "backup.example", "one.example"])
        self.assertEqual(result["alias.example"], ["198.51.100.1", "2001:db8::1"])
        generated = options(build(self.entry, template(), {"airport-1": fixture, "airport-2": source("other.example")}))
        self.assertEqual(generated["subscriptionHosts"], {"airport-1": result, "airport-2": {}})

    def test_hosts_conflicts_cycles_and_invalid_values_fail_without_secrets(self):
        invalid_hosts = (
            {"one.example": "one.example"},
            {"one.example": "two.example", "two.example": "one.example"},
            {"one.example": ["198.51.100.1", "alias.example"]},
            {"one.example": "https://private.invalid/?token=PRIVATE_FIXTURE"},
            {"one.example": "198.51.100.1", "ONE.EXAMPLE.": "198.51.100.2"},
            {"+.example": "198.51.100.1"},
        )
        for hosts in invalid_hosts:
            with self.subTest(hosts=hosts):
                fixture = source("one.example", hosts=hosts)
                with self.assertRaises(ConfigurationError) as caught:
                    extract_hosts(fixture, *extract_dns_policies(fixture))
                self.assertNotIn("PRIVATE_FIXTURE", str(caught.exception))
        with self.assertRaisesRegex(ConfigurationError, "conflicting hosts"):
            build(self.entry, template(), {
                "airport-1": source("one.example", hosts={"one.example": "198.51.100.1"}),
                "airport-2": source("ONE.EXAMPLE.", hosts={"ONE.EXAMPLE.": "198.51.100.2"}),
            })
        with self.assertRaisesRegex(ConfigurationError, "alias cycle when combined"):
            build(self.entry, template(), {
                "airport-1": source("one.example", hosts={"one.example": "two.example"}),
                "airport-2": source("two.example", hosts={"two.example": "one.example"}),
            })

    def test_output_boundary_and_utf8(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            repository = directory / "repo"
            repository.mkdir()
            with self.assertRaisesRegex(ConfigurationError, "outside"):
                write_private(repository / "secret.js", "PRIVATE", repository)
            destination = directory / "private" / "script.js"
            write_private(destination, "// 本地\n", repository)
            self.assertEqual(destination.read_bytes(), "// 本地\n".encode("utf-8"))
            link = directory / "link"
            try:
                link.symlink_to(repository, target_is_directory=True)
            except OSError:
                return  # Windows without symlink privilege still tests direct containment.
            with self.assertRaisesRegex(ConfigurationError, "outside"):
                write_private(link / "secret.js", "PRIVATE", repository)

    def test_errors_never_include_source_urls_or_yaml_text(self):
        with patch("configure_subscriptions.urlopen", side_effect=RuntimeError("https://fixture.invalid/a?token=PRIVATE_FIXTURE")):
            with self.assertRaises(ConfigurationError) as caught:
                build(self.entry, template())
        self.assertNotIn("PRIVATE_FIXTURE", str(caught.exception))
        self.assertNotIn("https://", str(caught.exception))
        with self.assertRaises(ConfigurationError) as caught:
            load_yaml("url: https://fixture.invalid/?token=PRIVATE_FIXTURE\ninvalid: [")
        self.assertNotIn("PRIVATE_FIXTURE", str(caught.exception))

    def test_duplicate_yaml_policies_fail_and_generation_is_deterministic(self):
        with self.assertRaisesRegex(ConfigurationError, "duplicate"):
            load_yaml("dns:\n  nameserver-policy:\n    one.example: 1.1.1.1\n    one.example: 8.8.8.8\n")
        sources = {"airport-1": source("one.example"), "airport-2": source("two.example")}
        first = build(self.entry, template(), sources)
        self.assertEqual(build(self.entry, first, sources), first)

    def test_download_uses_provider_header_and_full_source(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit):
                return b'proxies:\n  - {name: fixture, type: ss, server: one.example}\ndns:\n  nameserver-policy: {one.example: 1.1.1.1}\n'
        with patch("configure_subscriptions.urlopen", return_value=Response()) as request:
            result = options(build({"proxy-providers": {"airport-1": self.entry["proxy-providers"]["airport-1"]}}, template()))
        self.assertEqual(request.call_args.args[0].get_header("User-agent"), "fixture-client")
        self.assertEqual(result["subscriptionDnsPolicies"]["airport-1"], {"one.example": "1.1.1.1"})


if __name__ == "__main__":
    unittest.main()
