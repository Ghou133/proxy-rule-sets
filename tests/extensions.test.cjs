const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
function transform(input, landing = false, options = {}) {
  const file = fs.readFileSync(path.join(root, 'extensions', landing ? 'with-landing.js' : 'without-landing.js'), 'utf8');
  const context = vm.createContext({input: JSON.parse(JSON.stringify(input)), overrides: options});
  vm.runInContext(file + '\nObject.assign(OPTIONS, overrides); output = main(input);', context, {timeout: 2000});
  return JSON.parse(JSON.stringify(context.output));
}
const proxy = name => ({name, type: 'ss', server: 'example.invalid', port: 443, cipher: 'aes-128-gcm', password: 'fixture-only'});
const fixture = () => ({
  proxies: [proxy('日本 JP-A'), proxy('新加坡 SG-GPT'), proxy('香港 HK-A'), proxy('剩余流量 99GB')],
  'proxy-groups': [{name: '原选择', type: 'select', proxies: ['日本 JP-A', 'OpenAI']}, {name: 'OpenAI', type: 'select', proxies: ['新加坡 SG-GPT']}, {name: 'Claude', type: 'select', proxies: ['日本 JP-A']}],
  'rule-providers': {original: {type: 'file', behavior: 'classical', path: './original.yaml'}},
  rules: ['DOMAIN,a.example,DIRECT', 'RULE-SET,original,OpenAI', 'IP-CIDR,192.0.2.0/24,Claude,no-resolve', 'DOMAIN,a.example,DIRECT', 'MATCH,原选择'],
  dns: {enable: true, nameserver: ['system']}, tun: {enable: false}, 'mixed-port': 7890,
});
const landing = {name: 'fixture-exit', type: 'ss', server: 'landing.invalid', port: 443, cipher: 'aes-128-gcm', password: 'fixture-only'};
function group(config, name) { return config['proxy-groups'].find(g => g.name === name); }
function assertGraph(config) {
  const nodes = new Map(config.proxies.map(p => [p.name, p['dialer-proxy'] ? [p['dialer-proxy']] : []]));
  config['proxy-groups'].forEach(g => { assert.ok(!nodes.has(g.name), g.name); nodes.set(g.name, g.proxies || []); });
  const visited = new Set();
  function visit(name, stack) {
    if (['DIRECT', 'REJECT', 'REJECT-DROP', 'PASS'].includes(name)) return;
    assert.ok(nodes.has(name), 'Missing reference: ' + name);
    assert.ok(!stack.has(name), 'Cycle: ' + name);
    if (visited.has(name)) return;
    const next = new Set(stack); next.add(name);
    nodes.get(name).forEach(n => visit(n, next)); visited.add(name);
  }
  for (const name of nodes.keys()) visit(name, new Set());
}

test('subscription routing is replaced; only compact English groups remain', () => {
 const out=transform(fixture(),true,{landingProxy:landing});
 assert.equal(out['proxy-groups'][0].name,'Proxy');
 assert.deepEqual(out['proxy-groups'].filter(g=>!g.hidden).map(g=>g.name),['Proxy','AI','DMM','Relay']);
 assert.ok(group(out,'Proxy').proxies.includes('Exit'));
 assert.ok(out['proxy-groups'].every(g=>/^[A-Za-z]+$/.test(g.name)));
 assert.ok(!out['rule-providers'].original);
 assert.ok(!out.rules.some(r=>r.includes('a.example')||r.includes('original')));
 assert.equal(out.rules.at(-1),'MATCH,Proxy'); assertGraph(out);
});
test('AI has one manual selector, landing first, no automatic bypass',()=>{
 const out=transform(fixture(),true,{landingProxy:landing});
 assert.equal(group(out,'AI').type,'select');
 assert.deepEqual(group(out,'AI').proxies,['Exit','Proxy']);
 assert.ok(out['proxy-groups'].filter(g=>g.type==='fallback').every(g=>!g.proxies.includes('Exit')&&!g.proxies.includes('Proxy')));
 assert.equal(out.proxies.find(p=>p.name==='Exit')['dialer-proxy'],'Relay');
 assert.deepEqual(out.rules.slice(0,3),['RULE-SET,rsx-ai-0,AI','RULE-SET,rsx-ai-1,AI','RULE-SET,rsx-ai-2,AI']);
});
test('Relay selects preferred regions, with automatic fallback to other nodes',()=>{
 const out=transform(fixture(),true,{landingProxy:landing,transitHealthUrl:'https://health.invalid/'});
 assert.deepEqual(group(out,'Relay').proxies,['JP','HK','SG']);
 assert.deepEqual(group(out,'JP').proxies,['日本 JP-A','新加坡 SG-GPT','香港 HK-A']);
 assert.deepEqual(group(out,'HK').proxies,['香港 HK-A','日本 JP-A','新加坡 SG-GPT']);
 assert.equal(group(out,'JP').type,'fallback');
 assert.equal(group(out,'JP').url,'https://health.invalid/');
 assert.equal(group(out,'Latency'),undefined);
 assert.equal(group(out,'Relay').type,'select');
});
test('without landing has Proxy AI DMM visible and no chain',()=>{
 const out=transform(fixture());
 assert.deepEqual(out['proxy-groups'].filter(g=>!g.hidden).map(g=>g.name),['Proxy','AI','DMM']);
 assert.ok(!group(out,'Proxy').proxies.includes('Exit'));
 assert.deepEqual(group(out,'AI').proxies,['Auto','日本 JP-A','新加坡 SG-GPT','香港 HK-A']);
 assert.ok(!group(out,'AI').use); assertGraph(out);
 assert.ok(!out.proxies.some(p=>p.name==='Exit'));
});
test('idempotent reapplication and switching modes',()=>{
 for(const mode of [true,false]) {
  const opts=mode?{landingProxy:landing}:{};
  const first=transform(fixture(),mode,opts);
  assert.deepEqual(transform(first,mode,opts),first);
 }
 const out=transform(transform(fixture(),true,{landingProxy:landing}));
 assert.ok(!out.proxies.some(p=>p.name==='Exit')); assertGraph(out);
});
test('input immutable; DNS TUN ports and subscription nodes retained',()=>{
 const input=fixture(),before=JSON.stringify(input),out=transform(input);
 assert.equal(JSON.stringify(input),before);
 for(const key of ['dns','tun','mixed-port','proxies']) assert.deepEqual(out[key],input[key]);
 assert.equal(out.rules.filter(r=>r.startsWith('RULE-SET,rsx-source-')).length,21);
});
test('existing landing excluded from relay and retained unchanged',()=>{
 const input=fixture(); input.proxies.push({...landing,name:'MyExit'});
 const out=transform(input,true,{landingNodeName:'MyExit'});
 assert.deepEqual(out.proxies.find(p=>p.name==='MyExit'),input.proxies.at(-1));
 assert.ok(!group(out,'JP').proxies.includes('MyExit')); assertGraph(out);
});
test('missing prerequisites fail; old subscription group names are safe to replace',()=>{
 assert.throws(()=>transform(fixture(),true),/landingProxy/);
 assert.throws(()=>transform({}),/没有可用/);
 const input=fixture(); input['proxy-groups'].push({name:'Proxy',type:'select',proxies:['日本 JP-A']});
 assertGraph(transform(input)); input.proxies.push(proxy('Proxy'));
 assert.throws(()=>transform(input),/同名/);
});
test('provider regions prefer matching nodes but retain nonmatching fallback',()=>{
 const out=transform({'proxy-providers':{source:{type:'file',path:'./proxy.yaml'}}},true,{landingProxy:landing});
 assert.deepEqual(group(out,'JP').use,['source']);
 assert.ok(group(out,'JP').filter.endsWith('`.*'));
 assert.equal(group(out,'JP')['empty-fallback'],'REJECT'); assertGraph(out);
});
test('AI-only option still replaces subscription routing',()=>{
 const out=transform(fixture(),false,{includeLegacyRules:false});
 assert.equal(out.rules.length,4); assert.equal(Object.keys(out['rule-providers']).length,3);
 assert.ok(!group(out,'DMM'));
});

test('pure usage counters never become Auto or Relay candidates',()=>{
 const input=fixture(); input.proxies.push(proxy('12.78 GB | 200 GB'));
 const out=transform(input,true,{landingProxy:landing});
 for(const name of ['Auto','JP','Proxy','Relay']) {
  assert.ok(!group(out,name).proxies.includes('12.78 GB | 200 GB'));
 }
 assertGraph(out);
});

test('every preferred region retains all usable nodes as fallback, including Other',()=>{
 const input=fixture(); input.proxies.push(proxy('Germany DE-A'));
 const out=transform(input,true,{landingProxy:landing});
 assert.ok(group(out,'Relay').proxies.includes('Other'));
 assert.equal(group(out,'Other').proxies[0],'Germany DE-A');
 for(const name of group(out,'Relay').proxies) {
  assert.deepEqual(new Set(group(out,name).proxies),new Set(['日本 JP-A','新加坡 SG-GPT','香港 HK-A','Germany DE-A']));
 }
 assertGraph(out);
});

function multi(input) {
 const file=fs.readFileSync(path.join(root,'extensions/multi-subscription.js'),'utf8');
 const context=vm.createContext({input});
 vm.runInContext(file+'\noutput=main(input);',context,{timeout:2000});
 return JSON.parse(JSON.stringify(context.output));
}
const providersFixture=()=>({'proxy-providers':{
 a:{type:'inline',payload:[proxy('japan 01')]},
 b:{type:'inline',payload:[proxy('JAPAN 01')]}
}});
test('multi: providers only, no landing required, idempotent and no mutation',()=>{
 const input=providersFixture(), before=JSON.stringify(input), out=multi(input);
 assert.equal(JSON.stringify(input),before);
 assert.deepEqual(multi(out),out);
 assert.deepEqual(group(out,'Japan').use,['a','b']);
 assert.deepEqual(group(out,'Japan').proxies,[]);
 assert.equal(group(out,'Japan')['empty-fallback'],'REJECT');
 assert.equal(group(out,'Japan').type,'url-test');
 assert.equal(group(out,'Auto').interval,600);
 assert.equal(group(out,'Auto').lazy,true);
 assert.equal(out['proxy-providers'].a.override['additional-prefix'],'[P1] ');
 assert.equal(out['proxy-providers'].b.override['additional-prefix'],'[P2] ');
 assert.deepEqual(group(out,'AI').proxies,['Auto']);
 assert.deepEqual(group(out,'AI').use,['a','b']);
 assert.deepEqual(group(out,'DMM').use,['a','b']);
});
test('multi: hybrid regions use both inline and remote nodes, preserve networking',()=>{
 const input={...fixture(),...providersFixture()},out=multi(input);
 assert.deepEqual(group(out,'Japan').proxies,['日本 JP-A']);
 assert.deepEqual(group(out,'Japan').use,['a','b']);
 assert.deepEqual(out.dns,input.dns); assert.deepEqual(out.tun,input.tun);
 assert.equal(out['mixed-port'],input['mixed-port']);
 assert.ok(!out.rules.some(r=>r.includes('a.example')));
});
test('provider regex preserves case-insensitivity and filters prefixed info counters',()=>{
 const out=multi(providersFixture());
 const regex=s=>new RegExp(s.replace(/^\(\?i\)/,''),'i');
 assert.ok(group(out,'Japan').filter.startsWith('(?i)'));
 assert.ok(regex(group(out,'Japan').filter).test('[A] JAPAN 01'));
 const reject=regex(group(out,'Proxy')['exclude-filter']);
 assert.ok(reject.test('[A] TRAFFIC 20GB'));
 assert.ok(reject.test('[B] 12.78 GB | 200 GB'));
 assert.ok(!reject.test('[A] Japan 01'));
});
test('multi: missing and conflicting settings fail without leaking URL',()=>{
 assert.throws(()=>multi(fixture()),/proxy-providers/);
 const x=providersFixture(); x['proxy-providers'].a={type:'http',url:'https://example.invalid/SECRET',path:'a'};
 assert.throws(()=>multi(x),e=>!e.message.includes('SECRET'));
 const y=providersFixture(); Object.values(y['proxy-providers']).forEach(p=>p.override={'additional-prefix':'[A] '});
 assert.throws(()=>multi(y),/前缀/);
 const z=providersFixture(); Object.values(z['proxy-providers']).forEach(p=>{p.type='file';p.path='./same.yaml';});
 assert.throws(()=>multi(z),/path/);
});
test('legacy hybrid region fix also applies to existing modes',()=>{
 const out=transform({...fixture(),...providersFixture()});
 assert.deepEqual(group(out,'Japan').use,['a','b']);
 assert.equal(group(out,'Auto').interval,120);
});

test('multi: HTTP source defaults to independent DIRECT bootstrap',()=>{
 const input={'proxy-providers':{a:{type:'http',url:'https://subscription.invalid/nodes',path:'./a.yaml'}}};
 const out=multi(input);assert.equal(out['proxy-providers'].a.proxy,'DIRECT');
 assert.equal(out['proxy-providers'].a.url,input['proxy-providers'].a.url);
});

test('all desktop no-landing AI selectors expose every usable node directly',()=>{
 for(const out of [transform(fixture()),multi({...fixture(),...providersFixture()})]) {
  assert.deepEqual(group(out,'AI').proxies,['Auto','日本 JP-A','新加坡 SG-GPT','香港 HK-A']);
  assert.ok(!group(out,'AI').proxies.includes('Proxy'));
 }
});
test('independent multi landing version retains strict Exit and all providers',()=>{
 const file=fs.readFileSync(path.join(root,'extensions/multi-subscription-with-landing.js'),'utf8');
 const c=vm.createContext({input:providersFixture(),landing});
 vm.runInContext(file+';OPTIONS.landingProxy=landing;output=main(input);',c);
 const out=JSON.parse(JSON.stringify(c.output));
 assert.deepEqual(group(out,'AI').proxies,['Exit','Proxy']);
 assert.ok(group(out,'Proxy').proxies.includes('Exit'));
 assert.deepEqual(group(out,'JP').use,['a','b']);
 assert.equal(out.proxies.find(p=>p.name==='Exit')['dialer-proxy'],'Relay');
});

test('DMM exposes Japan nodes directly in all four PC variants',()=>{
 for(const name of ['with-landing.js','without-landing.js','multi-subscription.js','multi-subscription-with-landing.js']) {
  const c=vm.createContext({input:{...fixture(),...providersFixture()},landing});
  vm.runInContext(fs.readFileSync(path.join(root,'extensions',name),'utf8')+';OPTIONS.landingProxy=landing;output=main(input);',c);
  const dmm=JSON.parse(JSON.stringify(c.output['proxy-groups'].find(g=>g.name==='DMM')));
  assert.deepEqual(dmm.proxies,['Japan','日本 JP-A']);
  assert.deepEqual(dmm.use,['a','b']);assert.ok(!dmm.hidden);
  const filter=new RegExp(dmm.filter.replace(/^\(\?i\)/,''),'i');
  assert.ok(filter.test('[B] JAPAN 02'));assert.ok(!filter.test('[B] Hong Kong 01'));
 }
});

test('private single-file multi entry replaces original node pool without changing networking',()=>{
 const input=fixture(), sources=providersFixture()['proxy-providers'];
 const c=vm.createContext({input,sources,landing});
 vm.runInContext(fs.readFileSync(path.join(root,'extensions/multi-subscription-with-landing.js'),'utf8')+';OPTIONS.subscriptionProviders=sources;OPTIONS.landingProxy=landing;output=main(input);',c);
 const out=JSON.parse(JSON.stringify(c.output));
 assert.deepEqual(out.proxies.map(p=>p.name),['Exit']);
 assert.deepEqual(group(out,'Proxy').use,['a','b']);
 assert.deepEqual(group(out,'AI').proxies,['Exit','Proxy']);
 assert.deepEqual(out.dns,input.dns);assert.deepEqual(out.tun,input.tun);
 assert.deepEqual(input,fixture());
});
