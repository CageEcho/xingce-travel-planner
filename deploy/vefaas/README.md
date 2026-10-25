# 行策 · 火山引擎测试部署

本次发布为 M0 演示测试版，保留界面中的模拟资源声明。

- 产品入口：https://sbdn49ebov6bsukfs2496.apigateway-cn-beijing.volceapi.com/
- 公开演示无需登录，旧 `/login` 链接会跳转到首页。
- 后端文档：https://sldu8bctikc0lfbpk858p.apigateway-cn-beijing.volceapi.com/docs
- 地域：北京 `cn-beijing`
- 网关：`hydrogen-gw` / `gda7650ksm5372536jmg0`
- 前端应用：`xingce-travel-planner` / `5398c496da58`；函数 `ppxtk9j3`
- 后端应用：`xingce-travel-planner-api` / `13cc955d4313`；函数 `l1zna9dl`

## 数据与登录

后端开启 `PUBLIC_DEMO=true`、`AUTH_ENABLED=false`、`LLM_BUDGET_ENABLED=true`，浏览器自动获得签名的 HttpOnly 匿名 Cookie，按访客隔离需求卡、会话和方案。模型密钥与会话签名密钥只通过云端环境变量配置；无需用户输入 API Key。

## 模型使用边界

- 全站每日最多 500,000 Token（输入、输出与缓存 Token 均计入），每天北京时间 00:00 重置。
- 全站每日最多 60 次模型请求，每个自然分钟最多 6 次，同时最多 1 次模型调用。
- 单次输出上限：需求抽取 1,500、补问 800、行程编排 6,000 Token。
- 输入按 UTF-8 字节量、Schema 与协议余量保守预留，超过 40,000 的输入预算直接拒绝。
- 每次显式重试单独占用额度，关闭 SDK 隐式重试。调用前事务锁定并预留；收到有效 usage 后按实际消耗结算，失败或 usage 不明时保留预留额度。
- 达到额度、频率或并发上限时返回明确错误，前端不会自动重试额度错误。规则补问可继续，模型生成停止。
- 计数存放在演示 PostgreSQL 的 `llm_usage_budget` 表中，同一数据库重启后保留；演示库被云端替换或重建时计数也会清空。这是应用级保护，不是模型供应商的账户账单封顶；长期开放应使用持久化数据库和供应商账户额度。

演示 PostgreSQL 位于云端 `/tmp/xingce-travel-planner/pgdata`。后端保留一个实例、最多一个实例，以支持后台生成并避免不同实例拥有不同会话库。常驻实例会持续产生资源费用。实例替换、平台回收或重新发布时，测试会话和方案可能清空；模拟资源由启动脚本重新导入。需要长期保存数据时，应切换为独立 PostgreSQL，并移除演示数据库的单实例限制。

启动脚本先执行 Alembic 迁移，只在资源表为空且 `DEMO_MODE=true` 时导入种子数据。重复启动不会清空已有数据。

## 后续发布

更新代码后，先从项目根目录执行：

```bash
python3 deploy/vefaas/prepare.py
```

暂存目录只包含应用源码，排除本地密钥、数据库、个人文档和依赖目录。本机 `.vefaas` 绑定配置保留在各暂存目录中。

前端：

```bash
cd .deploy/vefaas/web
vefaas config list -o json
vefaas deploy --appId 5398c496da58 --yes
```

后端：

```bash
cd .deploy/vefaas/api
vefaas config list -o json
vefaas deploy --appId 13cc955d4313 --yes
```

前端构建将后端 URL 固化进 Next.js rewrite；更换后端地址时，必须修改构建命令中的 `BACKEND_URL` 并重新构建。

veFaaS 的代码目录无法写入 Next.js 图片缓存。构建脚本设置 `VEFAAS_DEPLOYMENT=true`，让前端直接提供已压缩的 WebP 文件；本地开发仍保留默认图片优化。

两个网关路由均已放行 `PATCH`。路由级自定义超时已关闭，函数请求超时为 300 秒；模型调用仍由应用超时及额度限制保护。CLI 创建应用的默认路由缺少 `PATCH`，创建新应用后需检查：

- 后端路由：`rdb754718ijfq83aumqs0`
- 前端路由：`rdb754t5et9bnt3ohsg0g`

## 本次验证

- Next.js 生产构建通过。
- 后端迁移、重复启动、空库导入、鉴权与会话创建冒烟通过。
- 168 项后端测试通过，包含匿名隔离、预算原子预留、失败/重试扣量、分钟限流与并发限制；前端 lint、生产构建与 API 错误处理测试通过。
- 公网首页与 API 代理可访问；匿名 Cookie 自动建立会话，旧登录链接跳回首页。
- 云端真实模型抽取成功；需求卡修改、确认、生成与方案读取通过。
- 东京三天测试方案完成，阻断性违规为 0。测试记录位于本机 `.deploy/vefaas/verification.json`。
- 浏览器登录、方案展示、客户版预览和 PDF 导出通过（导出文件约 883 KB）。
