#!/usr/bin/env python3
"""Native core integration: two HTTP subscriptions, prefixes, filters, reload, hybrid input."""
import argparse,json,subprocess,tempfile,time,threading,http.server
from pathlib import Path
from urllib.request import Request
from urllib.error import URLError
import yaml
from verify_relay_failover import ROOT,HTTP,port

def verify(core, directory, hybrid):
    node=lambda name: dict(name=name,type="http",server="127.0.0.1",port=9)
    payloads={"/a": [node("japan 01"),node("TRAFFIC 99GB")],"/b":[node("japan 01"),node("12.78 GB | 200 GB")]}
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            data=yaml.safe_dump({"proxies":payloads[self.path]}).encode()
            self.send_response(200);self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
    srv=http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
    threading.Thread(target=srv.serve_forever,daemon=True).start()
    source={"proxies":[node("Japan local")] if hybrid else [],"proxy-providers":{
        key:{"type":"http","proxy":"DIRECT","url":f"http://127.0.0.1:{srv.server_port}/{key}","path":f"./{key}.yaml","override":{"additional-prefix":f"[{key.upper()}] "}}
        for key in ("a","b")}}
    runner="const fs=require('fs'),vm=require('vm');const c={input:JSON.parse(fs.readFileSync(0,'utf8'))};vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';OPTIONS.subscriptionProviders=null;output=main(input);',c);process.stdout.write(JSON.stringify(c.output));"
    out=subprocess.run(["node","-e",runner,str(ROOT/"extensions/multi-subscription.js")],input=json.dumps(source),capture_output=True,text=True,encoding="utf-8",check=True)
    config=json.loads(out.stdout);api_port=port()
    config.update({"rule-providers":{},"rules":["MATCH,Proxy"],"mixed-port":0,"external-controller":f"127.0.0.1:{api_port}","secret":"","dns":{"enable":False},"tun":{"enable":False},"log-level":"silent"})
    for g in config["proxy-groups"]:
        if "url" in g:g["url"]=f"http://127.0.0.1:{srv.server_port}/a"
    directory.mkdir(parents=True)
    file=directory/"config.yaml";file.write_text(yaml.safe_dump(config,allow_unicode=True),encoding="utf-8")
    def api(path,method="GET"):
        with HTTP.open(Request(f"http://127.0.0.1:{api_port}"+path,method=method),timeout=8) as r:
            raw=r.read();return json.loads(raw) if raw else None
    process=None
    try:
        with (directory/"core.log").open("wb") as log:
            process=subprocess.Popen([str(core),"-d",str(directory),"-f",str(file)],stdout=log,stderr=log,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            for _ in range(100):
                try: version=api("/version");break
                except (URLError,OSError):
                    if process.poll() is not None:raise RuntimeError("Isolated core exited")
                    time.sleep(.1)
            else:raise RuntimeError("Core startup timed out")
            for _ in range(100):
                members=api("/proxies/Japan")["all"]
                if "[A] japan 01" in members and "[B] japan 01" in members:break
                time.sleep(.1)
            assert set(members)==set((["Japan local"] if hybrid else [])+["[A] japan 01","[B] japan 01"]),members
            assert set(api("/proxies/DMM")["all"]) == set(["Japan"] + members)
            assert "[A] japan 01" in api("/proxies/AI")["all"]
            assert "[B] japan 01" in api("/proxies/AI")["all"]
            assert api("/proxies/Hongkong")["now"]=="REJECT"
            assert not any("TRAFFIC" in n or "12.78" in n for n in api("/proxies/Proxy")["all"])
            payloads["/b"]=[node("[A]JP Node 02"),node("[A]HK Node 01")]
            api("/providers/proxies/b","PUT")
            assert "[B] [A]JP Node 02" in api("/proxies/Japan")["all"]
            assert "[B] japan 01" not in api("/proxies/Japan")["all"]
            assert "[B] [A]JP Node 02" in api("/proxies/DMM")["all"]
            assert "[B] [A]HK Node 01" not in api("/proxies/DMM")["all"]
            return {"mode":"hybrid" if hybrid else "providers-only","core":version,"http_sources":"PASS","prefix_collisions":"PASS","case_insensitive_regions":"PASS","empty_region_reject":"PASS","info_filter":"PASS","source_update":"PASS","DMM_direct_selection":"PASS","AI_direct_selection":"PASS","bracketed_region_codes":"PASS"}
    finally:
        if process:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        srv.shutdown();srv.server_close()
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--core",type=Path,required=True);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="multi-subscription-") as temp:
        results=[verify(args.core,Path(temp)/str(hybrid),hybrid) for hybrid in (False,True)]
    args.output.write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(results))
