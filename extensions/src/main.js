// Clash Verge Rev global extension. Built into standalone with/without-landing scripts.
// Configuration is transformed in memory. No filesystem/network APIs are used here.
function main(input) {
  const config = JSON.parse(JSON.stringify(input));
  const marker = "rule-sets-extension-v1";
  const generated = ["机场自动", "机场出口", "代理流量", "地区·日本", "地区·香港", "地区·新加坡", "地区·美国", "规则·DMM", "其他流量", "中转·日本优选", "中转·其他地区", "中转节点", "落地出口"];
  const previous = config["x-rule-sets-extension"] === marker;
  const serviceName = name => /^(AI|ChatGPT|OpenAI|Claude|Gemini)$/i.test(String(name || "").trim());
  const oldGroups = Array.isArray(config["proxy-groups"]) ? config["proxy-groups"] : [];
  const retiredServices = oldGroups.filter(g => serviceName(g.name)).map(g => g.name);
  const proxies = Array.isArray(config.proxies) ? config.proxies : [];
  if (!previous && oldGroups.some(g => generated.indexOf(g.name) >= 0)) {
    throw new Error("订阅中有与扩展脚本同名的策略组，请先改名：" + generated.filter(n => oldGroups.some(g => g.name === n)).join("、"));
  }
  if (!previous && proxies.some(p => p.name === "落地出口")) {
    throw new Error("订阅节点名“落地出口”与扩展保留名称冲突");
  }
  const originalRules = (config.rules || []).filter(r => !/^RULE-SET,rsx-/.test(r) && !(previous && r === "MATCH,其他流量"));
  const rules = originalRules.map(rule => {
    // Only replace the final action field, preserving matcher text and parameter order.
    const fields = String(rule).split(",");
    const index = fields[fields.length - 1] === "no-resolve" ? fields.length - 2 : fields.length - 1;
    if (retiredServices.indexOf(fields[index]) >= 0) fields[index] = "AI";
    return fields.join(",");
  });
  const groups = oldGroups.filter(g => !serviceName(g.name) && !(previous && generated.indexOf(g.name) >= 0));
  groups.forEach(g => {
    if (Array.isArray(g.proxies)) g.proxies = g.proxies.map(n => retiredServices.indexOf(n) >= 0 ? "AI" : n);
  });
  let landing = OPTIONS.landingProxy ? JSON.parse(JSON.stringify(OPTIONS.landingProxy)) : null;
  if (OPTIONS.landing && !landing) {
    landing = proxies.find(p => p.name === OPTIONS.landingNodeName);
    if (landing) landing = JSON.parse(JSON.stringify(landing));
  }
  if (OPTIONS.landing && (!landing || !landing.server || !landing.type)) {
    throw new Error("有落地版：请在脚本顶部设置 landingProxy，或把已有节点名填入 landingNodeName。无落地请使用另一版本。");
  }
  // Keep the original user node untouched; create one dedicated chained copy only.
  config.proxies = proxies.filter(p => !(previous && p.name === "落地出口"));
  const informational = /剩余|剩餘|流量|到期|过期|過期|套餐|官网|官網|订阅|訂閱|公告|通知|客服|traffic|expire|subscription|website/i;
  const usable = p => p && p.name && p.type && !informational.test(p.name)
    && !/^(direct|reject|reject-drop|pass|dns|compatible)$/i.test(p.type)
    && !p["dialer-proxy"] && p.name !== "落地出口"
    && !(landing && p.server === landing.server && p.port === landing.port)
    && !(OPTIONS.landing && p.name === OPTIONS.landingNodeName);
  const airport = config.proxies.filter(usable);
  const names = airport.map(p => p.name);
  const proxyProviders = config["proxy-providers"] || {};
  const providerNames = Object.keys(proxyProviders).filter(n => !(proxyProviders[n].override || {})["dialer-proxy"]);
  if (!names.length && !providerNames.length) throw new Error("没有可用的订阅节点；不会自动改为 DIRECT 中转");
  const japan = /日本|Japan|东京|東京|大阪|🇯🇵|(^|[\s_-])JPN?([\s_-]|$)/i;
  const hongkong = /香港|Hong[\s_-]*Kong|🇭🇰|(^|[\s_-])HK([\s_-]|$)/i;
  const singapore = /新加坡|Singapore|🇸🇬|(^|[\s_-])SG([\s_-]|$)/i;
  const usa = /美国|美國|United[\s_-]*States|🇺🇸|(^|[\s_-])USA?([\s_-]|$)/i;
  function automatic(name, members, url, providers) {
    const group = {name, type: "url-test", proxies: members, url, interval: 120, timeout: 5000, tolerance: 80, lazy: false};
    if (providers.length) {
      group.use = providers;
      group["exclude-filter"] = informational.source;
    }
    groups.push(group);
    return name;
  }
  automatic("机场自动", names, OPTIONS.healthUrl, providerNames);
  groups.push({name: "机场出口", type: "select", proxies: ["机场自动"].concat(names)});
  function region(name, expression) {
    const members = names.filter(n => expression.test(n));
    if (members.length) {
      automatic(name, members, OPTIONS.healthUrl, []);
    } else {
      // Never quietly change an explicitly regional policy to a different region.
      const group = {name, type: "select", proxies: ["REJECT"]};
      if (providerNames.length) { group.use = providerNames; group.filter = expression.source; }
      groups.push(group);
    }
  }
  region("地区·日本", japan);
  region("地区·香港", hongkong);
  region("地区·新加坡", singapore);
  region("地区·美国", usa);
  if (OPTIONS.landing) {
    const front = [];
    const jp = names.filter(n => japan.test(n));
    const rest = names.filter(n => !japan.test(n));
    const health = OPTIONS.transitHealthUrl || OPTIONS.healthUrl;
    if (jp.length) front.push(automatic("中转·日本优选", jp, health, []));
    if (rest.length || providerNames.length) front.push(automatic("中转·其他地区", rest, health, providerNames));
    groups.push({name: "中转节点", type: "fallback", proxies: front, url: health, interval: 60, timeout: 5000, lazy: false});
    landing.name = "落地出口";
    landing["dialer-proxy"] = "中转节点";
    config.proxies.push(landing);
  }
  const airportOptions = ["机场出口", "地区·日本", "地区·新加坡", "地区·美国"];
  groups.push({name: "AI", type: "select", proxies: (OPTIONS.landing ? ["落地出口"] : []).concat(airportOptions)});
  groups.push({name: "代理流量", type: "select", proxies: ["机场出口"].concat(OPTIONS.landing ? ["落地出口"] : [])});
  groups.push({name: "规则·DMM", type: "select", proxies: ["地区·日本"].concat(OPTIONS.landing ? ["落地出口"] : [])});
  groups.push({name: "其他流量", type: "select", proxies: ["机场出口"].concat(OPTIONS.landing ? ["落地出口"] : [])});
  const providers = config["rule-providers"] || {};
  if (!previous && Object.keys(providers).some(n => n.indexOf("rsx-") === 0)) throw new Error("rsx- 规则提供者名称已被订阅占用");
  Object.keys(providers).forEach(n => { if (n.indexOf("rsx-") === 0) delete providers[n]; });
  const prefix = [];
  MANIFEST.ai.forEach((source, index) => {
    const name = "rsx-ai-" + index;
    providers[name] = {type: "http", behavior: source.behavior, format: "yaml", url: source.url, path: "./ruleset/" + name + ".yaml", interval: 86400};
    prefix.push("RULE-SET," + name + ",AI");
  });
  if (OPTIONS.includeLegacyRules) {
    Object.keys(MANIFEST.providers).forEach(key => {
      const name = "rsx-" + key;
      providers[name] = JSON.parse(JSON.stringify(MANIFEST.providers[key]));
      providers[name].path = "./ruleset/" + name + "." + (providers[name].format === "yaml" ? "yaml" : "list");
    });
    const policyMap = {Proxies: "代理流量", DMM: "规则·DMM", Japan: "地区·日本", Hongkong: "地区·香港", Others: "其他流量"};
    MANIFEST.rules.filter(r => !r.startsWith("MATCH,")).forEach(rule => {
      let converted = rule.replace(/^RULE-SET,/, "RULE-SET,rsx-");
      converted = converted.replace(/<YOUR_POLICY_FOR_([^>]+)>/g, (_, policy) => {
        if (!policyMap[policy]) throw new Error("缺少上游策略映射：" + policy);
        return policyMap[policy];
      });
      prefix.push(converted);
    });
  }
  config.rules = prefix.concat(rules);
  if (!config.rules.some(r => /^(MATCH|FINAL),/.test(r))) config.rules.push("MATCH,其他流量");
  config["proxy-groups"] = groups;
  config["rule-providers"] = providers;
  config["x-rule-sets-extension"] = marker;
  return config;
}
