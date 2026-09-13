// Clash Verge Rev global extension. Built into standalone with/without-landing scripts.
// Configuration is transformed in memory. No filesystem/network APIs are used here.
function main(input) {
  const config = JSON.parse(JSON.stringify(input));
  const marker = "rule-sets-extension-v2";
  const previous = /^rule-sets-extension-v[12]$/.test(config["x-rule-sets-extension"] || "");
  const proxies = Array.isArray(config.proxies) ? config.proxies : [];
  const groups = [];
  const reserved = ["AI", "Proxy", "Auto", "Relay", "Latency", "Exit", "Japan", "Hongkong", "DMM"];
  if (proxies.some(p => reserved.includes(p.name) && !(previous && ["Exit", "落地出口"].includes(p.name)))) {
    throw new Error("订阅节点与扩展保留名称同名，请先修改节点名称");
  }
  let landing = OPTIONS.landingProxy ? JSON.parse(JSON.stringify(OPTIONS.landingProxy)) : null;
  if (OPTIONS.landing && !landing) {
    landing = proxies.find(p => p.name === OPTIONS.landingNodeName);
    if (landing) landing = JSON.parse(JSON.stringify(landing));
  }
  if (OPTIONS.landing && (!landing || !landing.server || !landing.type)) {
    throw new Error("有落地版：请在脚本顶部设置 landingProxy，或把已有节点名填入 landingNodeName。无落地请使用另一版本。");
  }
  // Keep the original user node untouched; create one dedicated chained copy only.
  config.proxies = proxies.filter(p => !(previous && ["Exit", "落地出口"].includes(p.name)));
  const informational = /剩余|剩餘|流量|到期|过期|過期|套餐|官网|官網|订阅|訂閱|公告|通知|客服|traffic|expire|subscription|website/i;
  const usable = p => p && p.name && p.type && !informational.test(p.name)
    && !/^(direct|reject|reject-drop|pass|dns|compatible)$/i.test(p.type)
    && !p["dialer-proxy"] && p.name !== "Exit"
    && !(landing && p.server === landing.server && p.port === landing.port)
    && !(OPTIONS.landing && p.name === OPTIONS.landingNodeName);
  const airport = config.proxies.filter(usable);
  const names = airport.map(p => p.name);
  const proxyProviders = config["proxy-providers"] || {};
  const providerNames = Object.keys(proxyProviders).filter(n => !(proxyProviders[n].override || {})["dialer-proxy"]);
  if (!names.length && !providerNames.length) throw new Error("没有可用的订阅节点；不会自动改为 DIRECT 中转");
  const japan = /日本|Japan|东京|東京|大阪|🇯🇵|(^|[\s_-])JPN?([\s_-]|$)/i;
  const hongkong = /香港|Hong[\s_-]*Kong|🇭🇰|(^|[\s_-])HK([\s_-]|$)/i;
  function automatic(name, members, url, providers) {
    const group = {name, hidden: true, "empty-fallback": "REJECT", type: "url-test", proxies: members, url, interval: 120, timeout: 5000, tolerance: 80, lazy: false};
    if (providers.length) {
      group.use = providers;
      group["exclude-filter"] = informational.source;
    }
    groups.push(group);
    return name;
  }
  automatic("Auto", names, OPTIONS.healthUrl, providerNames);
  groups.push({name: "Proxy", type: "select", proxies: ["Auto"].concat(names), ...(providerNames.length ? {use: providerNames, "exclude-filter": informational.source} : {})});
  function region(name, expression) {
    const members = names.filter(n => expression.test(n));
    if (members.length) {
      automatic(name, members, OPTIONS.healthUrl, []);
    } else {
      // Never quietly change an explicitly regional policy to a different region.
      const group = {name, hidden: true, type: "select", proxies: ["REJECT"]};
      if (providerNames.length) { group.use = providerNames; group.filter = expression.source; }
      groups.push(group);
    }
  }
  if (OPTIONS.includeLegacyRules) {
    region("Japan", japan);
    region("Hongkong", hongkong);
    groups.push({name: "DMM", hidden: true, type: "select", proxies: ["Japan"]});
  }
  if (OPTIONS.landing) {
    automatic("Latency", names, OPTIONS.transitHealthUrl || OPTIONS.healthUrl, providerNames);
    groups.push({name: "Relay", type: "select", proxies: ["Latency"].concat(names),
      ...(providerNames.length ? {use: providerNames, "exclude-filter": informational.source} : {})});
    landing.name = "Exit";
    landing["dialer-proxy"] = "Relay";
    config.proxies.push(landing);
  }
  // A select group never changes exit on failure. Airport bypass requires manual selection.
  groups.unshift({name: "AI", type: "select", proxies: OPTIONS.landing ? ["Exit", "Proxy"] : ["Proxy"]});
  // Replace subscription routing wholesale; retain subscription nodes and other settings only.
  const providers = {};
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
    const policyMap = {Proxies: "Proxy", DMM: "DMM", Japan: "Japan", Hongkong: "Hongkong", Others: "Proxy"};
    MANIFEST.rules.filter(r => !r.startsWith("MATCH,")).forEach(rule => {
      let converted = rule.replace(/^RULE-SET,/, "RULE-SET,rsx-");
      converted = converted.replace(/<YOUR_POLICY_FOR_([^>]+)>/g, (_, policy) => {
        if (!policyMap[policy]) throw new Error("缺少上游策略映射：" + policy);
        return policyMap[policy];
      });
      prefix.push(converted);
    });
  }
  config.rules = prefix.concat(["MATCH,Proxy"]);
  config["proxy-groups"] = groups;
  config["rule-providers"] = providers;
  config["x-rule-sets-extension"] = marker;
  return config;
}
