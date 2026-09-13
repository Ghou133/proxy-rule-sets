#!/usr/bin/env python3
"""Build mobile configs; private options are accepted only via an external JSON file."""
import argparse
import json
from pathlib import Path
from update_rules import write

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "AI": "https://raw.githubusercontent.com/iab0x00/ProxyRules/main/Rule/AI.txt",
    "LAN": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket/Lan/Lan.list",
    "China": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket/China/China.list",
    "ChinaDomain": "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket/China/China_Domain.list",
}
FILTER = r"^(?!\s*\d+(?:\.\d+)?\s*[KMGTkmgt][Bb]\s*[|/]\s*\d+(?:\.\d+)?\s*[KMGTkmgt][Bb]\s*$)((?!(剩余|剩餘|流量|套餐|到期|過期|过期|长期有效|官网|官網|订阅|訂閱|重置|公告|通知|客服|[Tt]raffic|[Ee]xpire|[Rr]eset|[Ss]ubscription|[Ww]ebsite)).)*$"
HEALTH = "http://www.gstatic.com/generate_204"


def render(landing, options=None):
    options = options or {}
    subscription = options.get("subscription", "SUBSCRIPTION")
    if any(c in subscription for c in ',\r\n='):
        raise ValueError("Subscription label contains configuration delimiters")
    head = """# Rule Sets — Shadowrocket
# Source: https://github.com/Ghou133/proxy-rule-sets
# Replace SUBSCRIPTION with the exact existing subscription label.
# With landing: bind Exit > Proxy Through to Transit in the app before use.
# No advertising filtering. No automatic bypass of Exit in the AI selector.

[General]
skip-proxy = 192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,localhost,*.local,captive.apple.com
tun-excluded-routes = 10.0.0.0/8,127.0.0.0/8,169.254.0.0/16,172.16.0.0/12,192.0.0.0/24,192.0.2.0/24,192.88.99.0/24,192.168.0.0/16,198.51.100.0/24,203.0.113.0/24,224.0.0.0/4,255.255.255.255/32,239.255.255.250/32,ff02::fb/128
dns-server = https://doh.pub/dns-query,https://dns.alidns.com/dns-query,223.5.5.5,119.29.29.29
fallback-dns-server = system
ipv6 = true
prefer-ipv6 = false
dns-direct-system = false
icmp-auto-reply = true
private-ip-answer = true
dns-direct-fallback-proxy = true
udp-policy-not-supported-behaviour = REJECT
block-quic = all-proxy
"""
    if landing:
        head += "close-if-proxy-chain-missing = true\n"
        node = options.get("landingProxy") or {"server": "exit.example.invalid", "port": 443,
                     "password": "YOUR_PASSWORD", "cipher": "2022-blake3-aes-128-gcm"}
        if any(any(c in str(node[k]) for c in ',\r\n') for k in ('server','port','password','cipher')):
            raise ValueError("Landing parameters contain configuration delimiters")
        head += ("\n[Proxy]\n# In the app, explicitly set this node's Proxy Through to Transit.\n"
                 f"Exit = ss,{node['server']},{node['port']},password={node['password']},method={node['cipher']},udp=1\n")
    pool = f"{subscription},use=true,policy-regex-filter={FILTER}"
    groups = [f"Proxy = select,Auto,Nodes{',Exit' if landing else ''},policy-select-name=Auto",
              f"AI = select,{'Exit,Proxy,policy-select-name=Exit' if landing else 'Proxy,policy-select-name=Proxy'}"]
    if landing:
        groups.append(f"Relay = select,{pool}")
    # One shared availability pool, no regional pools and no continuous lowest-latency race.
    groups += [f"Auto = fallback,{pool},url={HEALTH},interval=1800,timeout=5,hidden=1",
               f"Nodes = select,{pool},hidden=1"]
    if landing:
        health = options.get("transitHealthUrl") or HEALTH
        if any(c in health for c in ',\r\n'):
            raise ValueError("Health URL contains configuration delimiters")
        groups.append(f"Transit = fallback,Relay,Auto,url={health},interval=300,timeout=5,hidden=1")
    body = head + "\n[Proxy Group]\n" + "\n".join(groups) + "\n\n[Rule]\n"
    body += "# AI has priority over domestic rules.\n"
    body += f"RULE-SET,{SOURCES['AI']},AI\n"
    body += f"RULE-SET,{SOURCES['LAN']},DIRECT\n"
    body += f"RULE-SET,{SOURCES['China']},DIRECT\n"
    body += f"DOMAIN-SET,{SOURCES['ChinaDomain']},DIRECT\nGEOIP,CN,DIRECT\nFINAL,Proxy\n"
    return body + "\n[Host]\nlocalhost = 127.0.0.1\n"


def build(root=ROOT, options=None, output=None):
    directory = Path(output) if output else root / "clients/shadowrocket"
    if options and directory.resolve().is_relative_to(root.resolve()):
        raise ValueError("Private configurations must be written outside the public repository")
    result = {}
    for landing in (True, False):
        name = "with-landing.conf" if landing else "without-landing.conf"
        result[name] = render(landing, options)
        write(directory / name, result[name])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-options", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.private_options and not args.output:
        parser.error("--private-options requires an output outside the repository")
    build(options=json.loads(args.private_options.read_text("utf-8")) if args.private_options else None,
          output=args.output)
