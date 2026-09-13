#!/usr/bin/env python3
"""Isolated real-core test with local HTTP proxies; never reads or reloads the user's app."""
import argparse
import http.server
import json
import select
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, ProxyHandler
import yaml

ROOT = Path(__file__).resolve().parents[1]
HTTP = build_opener(ProxyHandler({}))


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args): pass
    def handle(self):
        try: super().handle()
        except (ConnectionError,OSError): pass
    def do_GET(self):
        self.send_response(204)
        self.send_header('Content-Length','0')
        self.end_headers()
    def do_CONNECT(self):
        if not self.server.available:
            self.send_error(502)
            return
        host,port = self.path.rsplit(':',1)
        self.server.connections += 1
        try:
            upstream = socket.create_connection((host,int(port)),timeout=2)
        except OSError:
            self.send_error(502)
            return
        self.send_response(200,'Connection established')
        self.end_headers()
        try:
            while True:
                ready,_,_=select.select([self.connection,upstream],[],[],3)
                if not ready: break
                for source in ready:
                    data=source.recv(65536)
                    if not data: return
                    (upstream if source is self.connection else self.connection).sendall(data)
        except OSError: pass
        finally: upstream.close()


def server():
    result=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    result.daemon_threads=True
    result.available=True
    result.connections=0
    threading.Thread(target=result.serve_forever,daemon=True).start()
    return result


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def verify(binary, directory, provider_mode=False):
    servers=[server() for _ in range(5)]
    origin,jp1,jp2,sg,exit_server=servers
    def proxy(name,srv):
        return {'name':name,'type':'http','server':'127.0.0.1','port':srv.server_port}
    nodes=[proxy('Japan 01',jp1),proxy('Japan 02',jp2),proxy('Singapore 01',sg)]
    input_config={'proxies':nodes}
    if provider_mode:
        input_config={'proxy-providers':{
            'first':{'type':'inline','payload':[nodes[2]]},
            'second':{'type':'inline','payload':nodes[:2]}}}
    health=f'http://127.0.0.1:{origin.server_port}/'
    payload={'input':input_config,'options':{'landingProxy':proxy('Exit',exit_server),
             'healthUrl':health,'transitHealthUrl':health,'includeLegacyRules':False}}
    runner="const fs=require('fs'),vm=require('vm');const c=JSON.parse(fs.readFileSync(0,'utf8'));vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';Object.assign(OPTIONS,options);result=main(input);',c);process.stdout.write(JSON.stringify(c.result));"
    transformed=subprocess.run(['node','-e',runner,str(ROOT/'extensions/with-landing.js')],
             input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,check=True)
    config=json.loads(transformed.stdout)
    # Local fixture rules replace remote data only in this isolated test instance.
    config['rule-providers']={}
    config['rules']=['MATCH,AI']
    api_port=port()
    config.update({'external-controller':f'127.0.0.1:{api_port}','secret':'',
                   'mixed-port':0,'tun':{'enable':False},'dns':{'enable':False},'log-level':'silent'})
    directory.mkdir(parents=True,exist_ok=True)
    config_file=directory/'config.yaml'
    config_file.write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False),encoding='utf-8')
    process=None
    def api(path,method='GET',body=None):
        request=Request(f'http://127.0.0.1:{api_port}'+path,
                 data=json.dumps(body).encode() if body is not None else None,
                 method=method,headers={'Content-Type':'application/json'})
        with HTTP.open(request,timeout=8) as response:
            raw=response.read()
            return json.loads(raw) if raw else None
    query='?url='+quote(health,safe='')+'&timeout=2000'
    def check_group(): api('/group/JP/delay'+query)
    try:
        with (directory/'core.log').open('wb') as log:
            process=subprocess.Popen([str(binary),'-d',str(directory),'-f',str(config_file)],
                        stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for _ in range(100):
                try: api('/version'); break
                except (URLError,OSError):
                    if process.poll() is not None: raise RuntimeError('Fixture core exited; inspect core.log')
                    time.sleep(.1)
            else: raise RuntimeError('Fixture core startup timed out')
            api('/proxies/Relay','PUT',{'name':'JP'})
            api('/proxies/AI','PUT',{'name':'Exit'})
            check_group()
            assert api('/proxies/JP')['now']=='Japan 01'
            api('/proxies/AI/delay'+query)
            jp1.available=False
            check_group()
            assert api('/proxies/JP')['now']=='Japan 02'
            jp2.available=False
            check_group()
            assert api('/proxies/JP')['now']=='Singapore 01'
            assert api('/proxies/Relay')['now']=='JP'
            api('/proxies/AI/delay'+query)
            jp1.available=True
            check_group()
            assert api('/proxies/JP')['now']=='Japan 01'
            exit_server.available=False
            try: api('/proxies/AI/delay'+query)
            except HTTPError: pass
            else: raise AssertionError('AI bypassed unavailable Exit')
            assert api('/proxies/AI')['now']=='Exit'
            api('/proxies/AI','PUT',{'name':'Proxy'})
            api('/proxies/Proxy','PUT',{'name':'Singapore 01'})
            # Independent request URL avoids reusing a failed test's connection pool.
            manual_query='?url='+quote(health+'manual',safe='')+'&timeout=2000'
            api('/proxies/AI/delay'+manual_query)
            return {'mode':'providers' if provider_mode else 'inline','preferred_region':'PASS',
                    'within_region_failover':'PASS','cross_region_failover':'PASS',
                    'preferred_region_recovery':'PASS','exit_failure_blocks_AI':'PASS','manual_bypass':'PASS'}
    finally:
        if process is not None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        for srv in servers: srv.shutdown(); srv.server_close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--core',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='relay-fixture-') as temp:
        results=[verify(args.core,Path(temp)/mode,mode=='providers') for mode in ('inline','providers')]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(results))
