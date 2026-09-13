#!/usr/bin/env python3
"""Prepare a private multi-subscription script from complete source configurations.

The global script cannot fetch subscription DNS settings itself. This helper retains
only explicit DNS dependencies of node server names, never general routing or DNS.
"""
import argparse
import copy
import ipaddress
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_USER_AGENT = "clash-verge/v2.4.5"
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024


class ConfigurationError(ValueError):
    """Messages deliberately omit private URLs, credentials and source text."""


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in result:
                raise ConfigurationError("YAML contains duplicate keys; resolve them before building.")
            result[key] = loader.construct_object(value_node, deep=deep)
        except TypeError:
            raise ConfigurationError("YAML contains an unsupported mapping key.") from None
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_yaml(text):
    try:
        result = yaml.load(text, Loader=_UniqueLoader)
    except (yaml.YAMLError, UnicodeError):
        raise ConfigurationError("Cannot parse configuration as UTF-8 YAML.") from None
    if not isinstance(result, dict):
        raise ConfigurationError("Configuration must be a YAML mapping.")
    return result


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise ConfigurationError("Cannot read a required local UTF-8 file.") from None


def _domain(value):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ConfigurationError("A node server or DNS selector has an invalid hostname.")
    result = value.rstrip(".").lower()
    if not result or any(c.isspace() for c in result) or any(c in result for c in "/:?#@, *+"):
        raise ConfigurationError("A node server or DNS selector has an unsupported hostname.")
    return result


def _selector(key):
    if not isinstance(key, str):
        raise ConfigurationError("DNS policy keys must be strings.")
    key = key.strip()
    if key.startswith("+."):
        return "suffix", _domain(key[2:])
    if key.startswith("*."):
        return "wildcard", _domain(key[2:])
    return "exact", _domain(key)


def _matches(key, hostname):
    kind, value = _selector(key)
    return hostname == value if kind == "exact" else (
        hostname.endswith("." + value) or (kind == "suffix" and hostname == value))


def _resolvers(value):
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value):
        return copy.deepcopy(value)
    raise ConfigurationError("A relevant DNS policy must contain a resolver string or nonempty string list.")


def _same_resolvers(left, right):
    return (left if isinstance(left, list) else [left]) == (right if isinstance(right, list) else [right])


def extract_dns_policies(source):
    """Return source-ordered policies relevant to actual node server hostnames."""
    proxies = source.get("proxies")
    if not isinstance(proxies, list) or not proxies:
        raise ConfigurationError("Each source must be complete Clash YAML with a nonempty proxies list; recursive providers are unsupported.")
    domains = []
    for proxy in proxies:
        if not isinstance(proxy, dict):
            raise ConfigurationError("Source proxies must be mappings.")
        server = proxy.get("server")
        if server is None and str(proxy.get("type", "")).lower() in {"direct", "reject", "pass"}:
            continue
        if not isinstance(server, str):
            raise ConfigurationError("Every source node must have a server string.")
        try:
            ipaddress.ip_address(server)
        except ValueError:
            hostname = _domain(server)
            if hostname not in domains:
                domains.append(hostname)
    dns = source.get("dns") or {}
    if not isinstance(dns, dict):
        raise ConfigurationError("Source DNS settings must be a mapping.")
    policies = {}
    for field in ("nameserver-policy", "proxy-server-nameserver-policy"):
        entries = dns.get(field) or {}
        if not isinstance(entries, dict):
            raise ConfigurationError("Source DNS policies must be mappings.")
        for compound_key, value in entries.items():
            if not isinstance(compound_key, str):
                raise ConfigurationError("DNS policy keys must be strings.")
            for key in compound_key.split(","):
                key = key.strip()
                # Selector dependencies cannot be expanded without changing semantics.
                try:
                    applicable = any(_matches(key, domain) for domain in domains)
                except ConfigurationError:
                    if domains:
                        raise ConfigurationError("Source uses a DNS selector whose node coverage cannot be proven (for example geosite or rule-set); provide explicit node hostname policies.") from None
                    applicable = False
                if not applicable:
                    continue
                resolver = _resolvers(value)
                equivalent = next((old for old in policies if _selector(old) == _selector(key)), None)
                if equivalent is not None and not _same_resolvers(policies[equivalent], resolver):
                    raise ConfigurationError("Source contains conflicting explicit node DNS policies; resolve them before building.")
                if equivalent is None:
                    policies[key] = resolver
    fallback = dns.get("proxy-server-nameserver")
    if fallback:
        resolver = _resolvers(fallback)
        for domain in domains:
            if not any(_matches(key, domain) for key in policies):
                policies[domain] = copy.deepcopy(resolver)
    return policies, domains


def _host_value(value):
    """Validate a hosts value and return its canonical identity and alias target."""
    if isinstance(value, str) and value:
        try:
            return ("ip", (str(ipaddress.ip_address(value)),)), None
        except ValueError:
            domain = _domain(value)
            return ("alias", domain), domain
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        try:
            return ("ip", tuple(str(ipaddress.ip_address(item)) for item in value)), None
        except ValueError:
            pass
    raise ConfigurationError("A relevant hosts value must be an IP address, nonempty IP list, or a hostname alias.")


def extract_hosts(source, policies, domains):
    """Retain only exact hosts required by node DNS and its bootstrap aliases."""
    hosts = source.get("hosts") or {}
    if not isinstance(hosts, dict):
        raise ConfigurationError("Source hosts settings must be a mapping.")
    dependencies = list(domains)
    for value in policies.values():
        for resolver in value if isinstance(value, list) else [value]:
            try:
                parsed = urlsplit(resolver if "://" in resolver else "//" + resolver)
                host = parsed.hostname
            except ValueError:
                raise ConfigurationError("A relevant DNS resolver has an invalid address.") from None
            if host:
                try:
                    ipaddress.ip_address(host)
                except ValueError:
                    dependencies.append(_domain(host))
    needed, visiting, visited = set(), set(), set()

    def visit(domain):
        if domain in visiting:
            raise ConfigurationError("Source hosts contains a cycle in a required node or DNS bootstrap alias chain.")
        if domain in visited:
            return
        visiting.add(domain)
        matched, identity, target = [], None, None
        for key, value in hosts.items():
            try:
                kind, hostname = _selector(key)
            except ConfigurationError:
                raise ConfigurationError("Source hosts uses an unsupported selector; its node/bootstrap coverage cannot be proven.") from None
            if kind != "exact":
                if _matches(key, domain):
                    raise ConfigurationError("A required hosts dependency uses a wildcard selector; provide an explicit hostname entry.")
                continue
            if hostname != domain:
                continue
            current, alias = _host_value(value)
            if matched and current != identity:
                raise ConfigurationError("Source hosts has conflicting entries for a required hostname.")
            matched.append(key)
            identity, target = current, alias
        needed.update(matched)
        if target is not None:
            visit(target)
        visiting.remove(domain)
        visited.add(domain)

    for domain in dependencies:
        visit(domain)
    # Original key spelling, values and source order remain intact.
    return {key: copy.deepcopy(value) for key, value in hosts.items() if key in needed}


def _check_cross_provider_hosts(host_map):
    combined = {}
    for entries in host_map.values():
        for key, value in entries.items():
            hostname = _domain(key)
            identity, _ = _host_value(value)
            if hostname in combined and combined[hostname] != identity:
                raise ConfigurationError("Subscriptions have conflicting hosts dependencies for a shared hostname; no entry was overwritten.")
            combined[hostname] = identity
    # Separate acyclic source chains may form a cycle after merging providers.
    for domain in combined:
        current, seen = domain, set()
        while current in combined and combined[current][0] == "alias":
            if current in seen:
                raise ConfigurationError("Subscription hosts dependencies form an alias cycle when combined.")
            seen.add(current)
            current = combined[current][1]


def _check_cross_provider(policies, domains):
    # Also catch suffix policies from one subscription influencing another's servers.
    for hostname in dict.fromkeys(host for values in domains.values() for host in values):
        matches = []
        for provider, entries in policies.items():
            for key, resolver in entries.items():
                if _matches(key, hostname):
                    matches.append((provider, resolver))
        for index, (provider, resolver) in enumerate(matches):
            if any(other != provider and not _same_resolvers(resolver, value) for other, value in matches[index + 1:]):
                raise ConfigurationError("Subscriptions have conflicting DNS dependencies for a shared node hostname; no policy was overwritten.")


def _fetch(provider):
    url = provider.get("url")
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
        if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ConfigurationError("Every subscription provider needs a valid HTTP(S) URL.")
        raw_headers = provider.get("header") or {}
        if not isinstance(raw_headers, dict):
            raise ConfigurationError("Provider headers must be a mapping.")
        headers = {}
        for name, value in raw_headers.items():
            if not isinstance(name, str) or not (isinstance(value, str) or isinstance(value, list) and all(isinstance(v, str) for v in value)):
                raise ConfigurationError("Provider headers must contain strings or string lists.")
            headers[name] = value if isinstance(value, str) else ", ".join(value)
        if not any(name.lower() == "user-agent" for name in headers):
            headers["User-Agent"] = DEFAULT_USER_AGENT
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            body = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(body) > MAX_DOWNLOAD_BYTES:
            raise ConfigurationError("A subscription exceeds the supported download size.")
        return body.decode("utf-8-sig")
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError("Subscription download failed; check the private URL, headers and local network. No URL was logged.") from None


def build(entry, template_text, sources=None):
    """Return private JS. sources maps provider names to full parsed source YAML."""
    providers = entry.get("proxy-providers")
    if not isinstance(providers, dict) or not providers:
        raise ConfigurationError("Entry must contain at least one proxy-provider.")
    sources = sources or {}
    if any(name not in providers for name in sources):
        raise ConfigurationError("An offline source does not match an entry provider.")
    policy_map, host_map, domains = {}, {}, {}
    for name, provider in providers.items():
        if not isinstance(name, str) or not isinstance(provider, dict) or provider.get("type") != "http":
            raise ConfigurationError("Entry supports named HTTP subscription providers only.")
        try:
            parsed = urlsplit(provider.get("url", ""))
            valid_url = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        except (ValueError, TypeError):
            valid_url = False
        if not valid_url:
            raise ConfigurationError("Every subscription provider needs a valid HTTP(S) URL.")
        source = sources[name] if name in sources else load_yaml(_fetch(provider))
        if not isinstance(source, dict):
            raise ConfigurationError("Offline source must be complete parsed Clash YAML.")
        policy_map[name], domains[name] = extract_dns_policies(source)
        host_map[name] = extract_hosts(source, policy_map[name], domains[name])
    _check_cross_provider(policy_map, domains)
    _check_cross_provider_hosts(host_map)
    marker = re.search(r"\bconst\s+OPTIONS\s*=\s*", template_text)
    if marker is None:
        raise ConfigurationError("Template must contain a JSON OPTIONS declaration.")
    try:
        options, length = json.JSONDecoder().raw_decode(template_text[marker.end():])
    except json.JSONDecodeError:
        raise ConfigurationError("Template OPTIONS must be valid JSON.") from None
    end = marker.end() + length
    if not isinstance(options, dict) or not re.match(r"\s*;\s*const\s+MANIFEST\b", template_text[end:]):
        raise ConfigurationError("Template must have OPTIONS followed by MANIFEST.")
    if not options.get("multiSubscription"):
        raise ConfigurationError("Select a multi-subscription template.")
    options["subscriptionProviders"] = copy.deepcopy(providers)
    options["subscriptionDnsPolicies"] = policy_map
    options["subscriptionHosts"] = host_map
    result = template_text[:marker.end()] + json.dumps(options, ensure_ascii=False, indent=2) + template_text[end:]
    return result.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").rstrip("\n") + "\n"


def write_private(output, text, repository_root=ROOT):
    output = Path(output).expanduser()
    root = Path(repository_root).resolve()
    # Reject lexical in-repository paths too, even when a symlink leads outside.
    if output.absolute().is_relative_to(root) or output.resolve().is_relative_to(root):
        raise ConfigurationError("Private output must be outside the Git repository.")
    resolved = output.resolve()
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(text, encoding="utf-8", newline="\n")
    except OSError:
        raise ConfigurationError("Cannot write private output outside the repository.") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry", type=Path, required=True, help="Private local YAML containing proxy-providers")
    parser.add_argument("--template", type=Path, required=True, help="Public or private multi-subscription JS template")
    parser.add_argument("--output", type=Path, required=True, help="Private output outside the Git repository")
    parser.add_argument("--source", action="append", default=[], metavar="PROVIDER=PATH", help="Use a full local source YAML instead of downloading; repeat per provider")
    args = parser.parse_args(argv)
    try:
        sources = {}
        for assignment in args.source:
            name, separator, path = assignment.partition("=")
            if not separator or not name or not path or name in sources:
                raise ConfigurationError("Each --source must uniquely specify PROVIDER=PATH.")
            sources[name] = load_yaml(_read(path))
        text = build(load_yaml(_read(args.entry)), _read(args.template), sources)
        write_private(args.output, text)
    except ConfigurationError as error:
        print("Configuration failed: " + str(error), file=sys.stderr)
        return 1
    print("Private script generated. Subscription addresses and connection details remain local.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
