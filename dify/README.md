# dify/ · 行策 Dify Chatflow 版本

完整说明见 [docs/13-Dify工作流与RAG知识库.md](../docs/13-Dify工作流与RAG知识库.md)。

| 文件 | 用途 |
| --- | --- |
| `build_knowledge.py` | 从 `seed/data` 生成知识库 Markdown（每条资源一个分段，带来源与校验状态，不含价格） |
| `knowledge/01-资源库-*.md` | 酒店（按城市）、餐厅（按城市）、景点、用车 → 「行策-资源库」；门票、路线 → 「行策-门票与路线」 |
| `knowledge/02-*.md`、`03-*.md`、`05-*.md` | 顾问 SOP、目的地攻略、知识库数据规范 → 「行策-业务规则与目的地攻略」 |
| `knowledge/04-*.md` | 典型案例与 80 份脱敏历史方案 → 「行策-定制案例库」 |
| `build_dsl.py` | 生成 Chatflow DSL：节点、提示词、Code 节点（需求卡校验、事实校验）都在这里 |
| `行策-定制方案助手.yml` | 生成好的 DSL，可在 Dify「导入 DSL 文件」直接使用（导入后需重新选择知识库） |
| `samples/` | 真实运行的对话记录 |
| `screenshots/` | 工作流画布截图 |

分段设置：自定义分隔符 `\n\n---\n\n`，最大长度 1500，不重叠；Embedding `qwen3-embedding-4b`，混合检索 + Rerank（`gte-rerank-v2`）。**资源库自身检索设置的 top_k 要调到 20**，否则多路检索时每路最多只返回 5 条。
