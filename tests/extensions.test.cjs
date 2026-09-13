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
test('one AI group; all three AI providers target it', () => {
  const output = transform(fixture());
  assert.equal(output['proxy-groups'].filter(g => /^(AI|OpenAI|ChatGPT|Claude|Gemini)$/.test(g.name)).length, 1);
  assert.deepEqual(output.rules.slice(0, 3), ['RULE-SET,rsx-ai-0,AI', 'RULE-SET,rsx-ai-1,AI', 'RULE-SET,rsx-ai-2,AI']);
  assert.ok(output.rules.includes('RULE-SET,original,AI'));
  assert.ok(output.rules.includes('IP-CIDR,192.0.2.0/24,AI,no-resolve'));
  assert.equal(group(output, '原选择').proxies[1], 'AI');
  assertGraph(output);
});
test('without landing adds no chained proxy or transit group', () => {
  const output = transform(fixture());
  assert.ok(!output.proxies.some(p => p.name === '落地出口'));
  assert.ok(!group(output, '中转节点'));
  assert.equal(group(output, 'AI').proxies[0], '机场出口');
});
test('landing uses physical Japanese fronts then other nodes, never DIRECT', () => {
  const output = transform(fixture(), true, {landingProxy: landing, transitHealthUrl: 'https://health.invalid/'});
  assert.deepEqual(group(output, '中转节点').proxies, ['中转·日本优选', '中转·其他地区']);
  assert.deepEqual(group(output, '中转·日本优选').proxies, ['日本 JP-A']);
  assert.ok(group(output, '中转·其他地区').proxies.includes('新加坡 SG-GPT'));
  assert.equal(output.proxies.find(p => p.name === '落地出口')['dialer-proxy'], '中转节点');
  assert.equal(group(output, 'AI').proxies[0], '落地出口');
  assert.equal(group(output, '中转节点').url, 'https://health.invalid/');
  assertGraph(output);
});
test('reapplication is byte-structurally idempotent for both modes', () => {
  for (const withLanding of [true, false]) {
    const options = withLanding ? {landingProxy: landing} : {};
    const first = transform(fixture(), withLanding, options);
    assert.deepEqual(transform(first, withLanding, options), first);
  }
});
test('switching landing mode removes only owned chain and keeps subscription', () => {
  const output = transform(transform(fixture(), true, {landingProxy: landing}));
  assertGraph(output);
  assert.ok(!output.proxies.some(p => p.name === '落地出口'));
  assert.ok(!group(output, '中转节点'));
  assert.equal(group(output, 'AI').proxies[0], '机场出口');
});
test('rules retain duplicates, order and terminal; DNS/TUN/proxy settings untouched', () => {
  const input = fixture(); const saved = JSON.stringify(input); const output = transform(input);
  assert.equal(JSON.stringify(input), saved);
  assert.deepEqual(output.dns, input.dns); assert.deepEqual(output.tun, input.tun);
  assert.equal(output['mixed-port'], input['mixed-port']);
  assert.deepEqual(output.proxies, input.proxies);
  assert.deepEqual(output.rules.slice(-5), ['DOMAIN,a.example,DIRECT','RULE-SET,original,AI','IP-CIDR,192.0.2.0/24,AI,no-resolve','DOMAIN,a.example,DIRECT','MATCH,原选择']);
  const legacy = output.rules.filter(r => /^RULE-SET,rsx-source-/.test(r));
  assert.equal(legacy.length, 21);
  assert.ok(legacy[19].endsWith(',DIRECT,no-resolve'));
});
test('existing landing node is copied without altering original', () => {
  const input = fixture(); input.proxies.push({...landing, name: 'MyExit'});
  const output = transform(input, true, {landingNodeName: 'MyExit'});
  assert.deepEqual(output.proxies.find(p => p.name === 'MyExit'), input.proxies.at(-1));
  assert.ok(!group(output, '中转·其他地区').proxies.includes('MyExit'));
  assertGraph(output);
});
test('missing landing, missing usable node and reserved names fail explicitly', () => {
  assert.throws(() => transform(fixture(), true), /landingProxy/);
  assert.throws(() => transform({}), /没有可用/);
  const input = fixture(); input['proxy-groups'].push({name:'机场自动',type:'select',proxies:['日本 JP-A']});
  assert.throws(() => transform(input), /同名/);
});
test('provider-only subscriptions supported without pretending Japanese discovery', () => {
  const output = transform({'proxy-providers': {source: {type:'file',path:'./proxy.yaml'}}, rules:[]}, true, {landingProxy:landing});
  assert.equal(group(output, '中转·日本优选'), undefined);
  assert.deepEqual(group(output, '中转·其他地区').use, ['source']);
  assert.deepEqual(group(output, '地区·日本').proxies, ['REJECT']);
  assert.equal(output.rules.at(-1), 'MATCH,其他流量');
  assertGraph(output);
});
test('AI-only option preserves subscription rules and avoids legacy providers', () => {
  const output = transform(fixture(), false, {includeLegacyRules:false});
  assert.equal(output.rules.length, fixture().rules.length + 3);
  assert.ok(!Object.keys(output['rule-providers']).some(k => k.startsWith('rsx-source-')));
});
