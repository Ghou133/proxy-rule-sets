#!/usr/bin/env python3
"""Optional actual-core import test in a disposable directory, never the user's config."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    if work == ROOT or work.is_relative_to(ROOT):
        raise ValueError("Runtime scratch directory must be outside the deliverable repository")
    work.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    providers, expected = {}, {}
    for number, path in enumerate(ROOT.glob("mihomo/**/*.yaml")):
        data = path.read_bytes()
        name = f"local-{number}"
        destination = work / f"{name}.yaml"
        destination.write_bytes(data)
        providers[name] = {"type": "file", "behavior": "classical", "format": "yaml", "path": str(destination)}
        expected[name] = {"file": path.relative_to(ROOT).as_posix(), "rules": len(yaml.safe_load(data)["payload"])}
    external = json.loads((ROOT / "artifacts/external_dependencies.json").read_text("utf-8"))
    for number, item in enumerate(external):
        name = f"external-{number}"
        pinned = item["selected_url"].replace("/master/", "/" + item["commit"] + "/", 1)
        with urllib.request.urlopen(pinned, timeout=40) as response:
            data = response.read()
        expected_hash = item["yaml_sha256"] if item["format"] == "yaml" else item["original_sha256"]
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise ValueError("Pinned third-party bytes do not match audited hash")
        destination = work / (name + "." + ("yaml" if item["format"] == "yaml" else "list"))
        destination.write_bytes(data)
        providers[name] = {"type": "file", "behavior": item["behavior"], "format": item["format"], "path": str(destination)}
        expected[name] = {"url": pinned, "rules": (item["yaml_count"] if item["format"] == "yaml" else item["original_count"]) - len(item["mihomo_unsupported"])}
    # No listening proxy ports, no TUN, no routing changes; loopback controller only.
    config = {"external-controller": f"127.0.0.1:{port}", "allow-lan": False, "mode": "rule",
              "log-level": "info", "rule-providers": providers,
              "rules": [f"RULE-SET,{name},DIRECT" for name in providers] + ["MATCH,DIRECT"]}
    (work / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    log_path = work / "core.log"
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(args.binary.resolve()), "-d", str(work), "-f", str(work / "config.yaml")], stdout=log, stderr=subprocess.STDOUT, **kwargs)
        try:
            deadline = time.monotonic() + 90
            state = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Core exited; inspect " + str(log_path))
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/providers/rules", timeout=2) as response:
                        state = json.load(response)["providers"]
                    if all(name in state and state[name].get("ruleCount") == entry["rules"] for name, entry in expected.items()):
                        break
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(0.3)
            else:
                raise RuntimeError("Counts did not match: " + json.dumps({name: {"expected": entry["rules"], "actual": (state or {}).get(name, {}).get("ruleCount")} for name, entry in expected.items()}))
            result = {"core": subprocess.check_output([str(args.binary.resolve()), "-v"], text=True).strip(),
                      "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                      "providers": {name: {**entry, "actual": state[name]["ruleCount"]} for name, entry in expected.items()},
                      "local_import": "PASS", "external_import": "PASS_WITH_KNOWN_UNSUPPORTED",
                      "known_external_unsupported_count": sum(len(e["mihomo_unsupported"]) for e in external)}
            (work / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, indent=2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
