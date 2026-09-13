# 多订阅版

多个订阅由 Mihomo 原生 `proxy-providers` 下载；不需要转换网站、服务器或后台合并程序。默认无落地。原有两个脚本继续保留。

1. 下载 [本地配置模板](multi-subscriptions.example.yaml)，只在本地填写两个订阅 URL。优先使用服务商提供的 Clash YAML 节点订阅。
2. 在 Clash Verge Rev 中创建本地配置，导入填写后的 YAML 并选择它。
3. 将 [multi-subscription.js](multi-subscription.js) 内容放入全局扩展脚本，保存后检查生效配置。旧全局覆写如另行追加代理组，需要自行停用该追加内容。

本项目不会自动修改正在使用的配置。公开模板没有连接凭据；本地配置含私人订阅链接，请勿上传 GitHub。

## 日常使用

`Proxy` 在最上方，`Auto` 自动选节点，也可以手动选择带 `[A]` / `[B]` 前缀的节点。`AI` 统一管理 ChatGPT、Claude、Gemini，默认走 `Proxy`。历史规则需要的地区组仍保留，内部保持规则原始顺序。

增加第三个订阅：复制 YAML 中一个 provider，改名、URL、独立 path 与前缀为 `[C] `；所有节点选择组自动接入，不必逐组修改。删除订阅直接删除该 provider。不要使用“订阅A”等前缀，它会被信息节点过滤器排除。不同 provider 不可使用相同缓存路径或前缀。

脚本替换订阅的规则、规则提供者和代理组，保留输入的节点、节点提供者及网络设置。远程订阅里的 DNS、TUN、规则、代理组不被导入。**新建本地配置不会自动继承旧订阅的网络设置**：有需要应复制原有效配置中的 DNS、TUN、端口等设置；交付的私人入口已保留本机有效网络配置。不要把完整运行配置发布到仓库。

## 下载与测速

订阅每日更新，下载默认 `DIRECT`，避免首次下载依赖自身节点。若订阅地址直连不可达，应使用可独立工作的下载代理或已有缓存；不要把下载出口指向只依赖该订阅的 `Proxy`。只有代理组而没有实际节点的 YAML 不能作为节点源；不会递归展开嵌套订阅。

多订阅版组测速为 600 秒、lazy=true；provider 健康检查模板为 1800 秒、lazy=true。两种检查分别受核心调度，不承诺零探测或精确耗电值；测速是节点到测试网站的连通性能，并非到落地服务器的真实延迟。

如要自行启用落地，可在**私人脚本副本**顶部设置 `landing: true` 与 `landingProxy`，沿用现有落地链逻辑。`landingNodeName` 仅能查找本地 `proxies` 中的节点，不能从尚未下载的 provider 中查找。AI 默认 Exit，失败不会自动改走普通代理；只能手动选择 Proxy。

## 验证与依据

`python scripts/build_extensions.py` 生成三版脚本，共享 `extensions/src/main.js`。`node --test tests/extensions.test.cjs` 验证地区筛选、混合输入、前缀、重复执行、缺失配置和旧版本回归。

依据：[Mihomo proxy-providers](https://wiki.metacubex.one/config/proxy-providers/)、[Clash Verge Rev 配置](https://www.clashverge.dev/guide/config.html)。其他 AI 对话中的补丁与测试数量不作为验证证据；本仓库以实际代码和本地测试为准。手机与 Android 不在此次修改范围内。

真实 Mihomo v1.19.29 集成验证见 [报告](../artifacts/multi_subscription_verification.json)，覆盖 HTTP 双源、前缀、筛选、更新和混合节点。复现：

```sh
python scripts/verify_multi_subscription.py --core /path/to/mihomo --output artifacts/multi_subscription_verification.json
```

该测试启动独立临时核心与本机模拟订阅，不读取、连接或重载用户正在运行的代理配置。
