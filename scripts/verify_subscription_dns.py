#!/usr/bin/env python3
"""Offline native-core regression for source-specific proxy hostname DNS."""
import argparse,json,socketserver,struct,subprocess,tempfile,threading,time
from pathlib import Path
from urllib.parse import quote
import yaml
from verify_relay_failover import ROOT,HTTP,port,server

class DNS(socketserver.BaseRequestHandler):
    def handle(self):
        data,sock=self.request
        pos=12
        while data[pos]:pos+=1+data[pos]
        end=pos+5
        question=data[12:end]
        good=self.server.good
        response=data[:2]+struct.pack('!HHHHH',0x8180 if good else 0x8183,1,1 if good else 0,0,0)+question
        if good:response+=b'\xc0\x0c'+struct.pack('!HHIH',1,1,1,4)+b'\x7f\x00\x00\x01'
        self.server.queries+=1;sock.sendto(response,self.client_address)

def dns(good):
    srv=socketserver.ThreadingUDPServer(('127.0.0.1',0),DNS);srv.good=good;srv.queries=0
    threading.Thread(target=srv.serve_forever,daemon=True).start();return srv

def verify(core,folder,enabled):
    good,bad=dns(True),dns(False);origin,proxy=server(),server();process=None
    try:
        url=f'http://127.0.0.1:{origin.server_port}/'
        options={'subscriptionProviders':None,'includeLegacyRules':False,'proxyServerNameserver':[f'127.0.0.1:{bad.server_address[1]}'],'healthUrl':url,'subscriptionDnsPolicies':{'fixture':{'node.fixture.invalid':[f'127.0.0.1:{good.server_address[1]}']}} if enabled else {}}
        data={'input':{'proxy-providers':{'fixture':{'type':'inline','payload':[{'name':'Fixture','type':'http','server':'node.fixture.invalid','port':proxy.server_port}]}}},'options':options}
        runner="const fs=require('fs'),vm=require('vm'),c=JSON.parse(fs.readFileSync(0,'utf8'));vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';Object.assign(OPTIONS,options);result=main(input);',c);process.stdout.write(JSON.stringify(c.result));"
        result=subprocess.run(['node','-e',runner,str(ROOT/'extensions/multi-subscription.js')],input=json.dumps(data),capture_output=True,text=True,encoding='utf-8',check=True)
        c=json.loads(result.stdout);api=port();c.update({'rule-providers':{},'rules':['MATCH,Proxy'],'mixed-port':0,'external-controller':f'127.0.0.1:{api}','secret':'','tun':{'enable':False},'log-level':'silent'})
        c['dns'].update({'enable':True,'listen':f'127.0.0.1:{port()}','nameserver':[f'127.0.0.1:{bad.server_address[1]}']})
        folder.mkdir();file=folder/'config.yaml';file.write_text(yaml.safe_dump(c),encoding='utf-8')
        with (folder/'core.log').open('wb') as log:
            process=subprocess.Popen([str(core),'-d',str(folder),'-f',str(file)],stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for _ in range(60):
                try:
                    with HTTP.open(f'http://127.0.0.1:{api}/version',timeout=1) as response:version=json.load(response)
                    break
                except Exception:
                    if process.poll() is not None:raise RuntimeError('Fixture core exited')
                    time.sleep(.1)
            else:raise RuntimeError('Fixture core timed out')
            success=False
            try:
                with HTTP.open(f'http://127.0.0.1:{api}/providers/proxies/fixture/'+quote('[P1] Fixture',safe='')+'/healthcheck?timeout=2000&url='+quote(url,safe=''),timeout=4) as response:success='delay' in json.load(response)
            except Exception:pass
            assert success==enabled, 'Source DNS dependency was not honored'
            assert (good.queries>0 if enabled else bad.queries>0)
            return {'source_policy':enabled,'expected_connection':enabled,'matched_expectation':True,'core':version,'resolver_exercised':True}
    finally:
        if process is not None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        for srv in (good,bad,origin,proxy):srv.shutdown();srv.server_close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--core',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='subscription-dns-') as temp:results=[verify(args.core,Path(temp)/str(enabled),enabled) for enabled in (False,True)]
    args.output.write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(results))
