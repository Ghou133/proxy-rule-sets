#!/usr/bin/env python3
"""Build self-contained Clash Verge Rev scripts; public output never contains credentials."""
import json
from pathlib import Path
import yaml
from update_rules import write, json_text

ROOT = Path(__file__).resolve().parents[1]


def build(root=ROOT):
    fragment = yaml.safe_load((root / "examples/mihomo-rules.yaml").read_text("utf-8"))
    ai = json.loads((root / "extensions/ai_sources.json").read_text("utf-8"))
    manifest = {"providers": fragment["rule-providers"], "rules": fragment["rules"], "ai": ai}
    core = (root / "extensions/src/main.js").read_text("utf-8")
    output = {}
    for name, landing, multi in (("with-landing.js", True, False), ("without-landing.js", False, False), ("multi-subscription.js", False, True), ("multi-subscription-with-landing.js", True, True)):
        options = {"landing": landing, "landingNodeName": "落地节点", "landingProxy": None,
                   "transitHealthUrl": "", "healthUrl": "https://www.gstatic.com/generate_204", "includeLegacyRules": True}
        options["multiSubscription"] = multi
        if multi:
            options["subscriptionProviders"] = {
                f"airport-{i}": {"type": "http", "url": "这里填订阅地址",
                    "path": f"./proxy_providers/airport-{i}.yaml", "interval": 86400, "proxy": "DIRECT",
                    "header": {"User-Agent": ["clash-verge/v2.4.5"]},
                    "override": {"additional-prefix": f"[{label}] "},
                    "health-check": {"enable": True, "url": "https://www.gstatic.com/generate_204", "interval": 1800, "lazy": True}}
                for i, label in ((1, "A"), (2, "B"))}
            options["proxyServerNameserver"] = ["https://223.5.5.5/dns-query"]
        text = ("// Clash Verge Rev 全局扩展脚本：" + ("有落地" if landing else "无落地") + "\n"
                "// Source: https://github.com/Ghou133/proxy-rule-sets\n"
                "// 公开模板不包含节点密码。AI 为统一策略组。\n"
                "const OPTIONS = " + json.dumps(options, ensure_ascii=False, indent=2) + ";\n"
                "const MANIFEST = " + json.dumps(manifest, ensure_ascii=False, indent=2) + ";\n\n" + core)
        output["extensions/" + name] = text
    for path, text in output.items():
        write(root / path, text)
    from build_shadowrocket import build as build_shadowrocket
    build_shadowrocket(root=root)
    return output


if __name__ == "__main__":
    build()
