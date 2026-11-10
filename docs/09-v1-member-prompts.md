# 三名成员 v1 开发 Prompt

分发前请先合入本轮契约 PR，三人基于同一个 main 开发。以下每段可完整复制给对应成员的 Codex；已包含范围和交付约束。

## 成员 A

```text
你是成员 A，负责 v1 正式版前端，在 feature/v1-frontend 开发，仅修改 frontend/ 及 docs/deliveries/A.md。

先阅读 AGENTS.md、README.md 和 docs/ 下全部设计文档，再检查当前代码。以 docs/08-v1-release-contract.md 冻结的 v1 功能、接口和职责为准，05 补充通用契约，02 的五表 SQL 为数据库依据。不要按 01 的旧字段/旧路由重建项目。你在多人协作仓库中，不能覆盖其他成员修改；只在自己的范围扩展现有实现，不提交密钥或测试输出。公共契约有冲突先问负责人，不能自行改名、增表、改方法或响应。
从负责人合入本轮审查后的共同 main 创建自己的功能分支；不要假定本地已有最新基线，先检查 git 状态和远端。保持 run_simulation / SimulationResult / complete_run 兼容，单实例和原子持久化规则不变。


完成 08 第 2、5 节全部前端效果：总览（含 P50/P95/趋势/错误分布）、Agent 创建/修改/启停、Task/Run 列表和详情、同一 Task 多次模拟执行及 Agent 绑定、完整 Trace 树与相对时间线/Span/Event、全局日志多条件查询、Agent/工具性能、两个实验案例的执行/历史/前后耗时和计划。导航和直接进入路由可用，覆盖加载/空/错误/分页/重试。真实模型不作为 v1 可执行入口。

沿用 api/client.ts、types、tree，拆分 App.vue；根据 05/08 定义精确类型，普通请求 15 秒、实验请求 150 秒，时间提交 UTC。Trace 必须取完所有 Span/Event 分页后构树；离开页面停止轮询和失效请求，终态再查轨迹。未交付接口可显式 mock 先开发，交付前必须切换真实后端并记录验证，不把 mock 成功当正式验收。

先按冻结字段建页面和客户端，负责人合入 B 第一批接口后真实联调，按团队集成节奏更新基线。你拥有前端依赖及 lock、frontend/tests 浏览器测试；不得修改后端来适配页面。新增测试覆盖 Agent PATCH 跨域、历史 Run/筛选、105+ Span、日志跳转、统计 null/0 与实验超时。执行 npm ci、npm test、npm run build，并在真实后端上运行浏览器测试。交付 A.md 列出 V01–V09 对应页面、修改文件、命令/结果、基线与提交 SHA、未完成项。提交你的分支或 PR 给负责人，不自行合入 main。
```

## 成员 B

```text
你是成员 B，负责 v1 后端与数据库，在 feature/v1-backend 开发。拥有除 recorder/simulator/adapters 外的 backend/app、backend/tests/conftest.py、test_database.py、test_cors.py、新增 tests/backend/、database/、后端依赖/lock、根目录运行配置，以及 docs/deliveries/B.md。不能修改 C 的契约/模拟器/系统测试和 A 的前端。

先阅读 AGENTS.md、README.md 和 docs/ 下全部设计文档，再检查当前代码。以 docs/08-v1-release-contract.md 冻结的 v1 功能、接口和职责为准，05 补充通用契约，02 的五表 SQL 为数据库依据。不要按 01 的旧字段/旧路由重建项目。你在多人协作仓库中，不能覆盖其他成员修改；只在自己的范围扩展现有实现，不提交密钥或测试输出。公共契约有冲突先问负责人，不能自行改名、增表、改方法或响应。
从负责人合入本轮审查后的共同 main 创建自己的功能分支；不要假定本地已有最新基线，先检查 git 状态和远端。保持 run_simulation / SimulationResult / complete_run 兼容，单实例和原子持久化规则不变。


第一批先交付 08 约定的可选 simulation_config.agent_ids Schema、创建 Run 前 Agent 存在/ACTIVE 校验、标准化 config 传递、Agent CRUD（无删除）及 Task/Run 查询分页。与负责人确认合入后供 A/C 使用。所有原型请求继续兼容；Schema 扩展不得要求原型无绑定请求提供 Agent。

随后实现 05/08 全部 v1 API：全局日志及过滤、overview/P50/P95、趋势和 Agent/工具/错误统计（含 08 的扩展字段），严格遵守 UTC 窗口、分母、nullable、分页与稳定排序。所有输入输出声明 Pydantic 模型和 OpenAPI，统一错误体，PATCH CORS 保持可用，不因当前 OpenAPI 缺接口而降级需求。保持参数化 SQL、完整树及单事务、约束回滚和并发完成冲突。

按 08 第 6 节实现 TRACE_QUERY_INDEX / ERROR_PARTIAL_INDEX、1000/10000/100000 规模、真实 EXPLAIN 对比、三次中位数、同步接口及完整结果模型；隔离实验数据和索引，不能修改业务库索引。结果原子保存 backend/var/benchmarks.json，处理并发/超时/损坏；补 BENCHMARK_ENABLED，按冻结默认值运行。迁移用新增编号，不改已应用 001；无需求不增加业务表。维护依赖和安装说明变更交负责人更新 README。

你不修改 C 的原型系统测试；原型路径子集断言本轮已修复，保持通过。EventData/SpanData 如需改动先协调负责人/C。新增 API/数据库测试覆盖本文件所有过滤/校验/统计边界、实验隔离与结果持久化、Agent 身份验证；依赖真实 PostgreSQL *_test 库测试，不以 SQLite 或 skipped 测试冒充通过。执行 scripts/test_backend.py、Ruff，记录 B.md 的功能/文件/命令结果/Schema 交付 SHA/迁移与配置/未完成项。仅提交自己的分支或 PR，交负责人集成。
```

## 成员 C

```text
你是成员 C，负责 v1 Recorder、模拟器、数据生成和系统测试，在 feature/v1-simulator 开发。拥有 backend/app/recorder、simulator、adapters，backend/tests/test_recorder.py、tests/system/、新增 tests/simulator/、scripts/（冻结 test_backend.py 不改）及 docs/deliveries/C.md。不得修改 B 的 schemas/services/依赖/迁移/共享 fixture 或 A 的 frontend/tests。

先阅读 AGENTS.md、README.md 和 docs/ 下全部设计文档，再检查当前代码。以 docs/08-v1-release-contract.md 冻结的 v1 功能、接口和职责为准，05 补充通用契约，02 的五表 SQL 为数据库依据。不要按 01 的旧字段/旧路由重建项目。你在多人协作仓库中，不能覆盖其他成员修改；只在自己的范围扩展现有实现，不提交密钥或测试输出。公共契约有冲突先问负责人，不能自行改名、增表、改方法或响应。
从负责人合入本轮审查后的共同 main 创建自己的功能分支；不要假定本地已有最新基线，先检查 git 状态和远端。保持 run_simulation / SimulationResult / complete_run 兼容，单实例和原子持久化规则不变。


先完善 research 的成功/失败/seed/树/Event，按 08 第 4 节加入最多一次重试成功场景，严格将根/角色/重试计入 Span 预算，限制 500 Span/2000 Event。固定 seed 决定结构和随机结果，事件 ID 和时间仍动态生成。保持普通失败、异常无 Trace 和根唯一/无环/引用合法。Recorder 单 Run 独立，保持顺序执行，不共享栈并发。

待负责人集成 B 的 agent_ids Schema 后，基于该基线实现 Agent 身份绑定（AGENT 与其 LLM/TOOL 使用对应 ID、WORKFLOW null），按顺序映射角色；不要自行编辑 B 的 SimulationConfig，不自行查数据库或生成假 agent_id。无绑定旧请求仍可运行。run_simulation 和 SimulationResult 签名保持 05/08，不由 Recorder 提交数据库。

提供 08 第 7 节 scripts/generate_data.py 标准库 HTTP 工具，所有参数和默认值按契约，累计实际落库 Span 至少 100000，打印可复验摘要与 ID；查询可有限重试，POST 不盲重试，错误退出非零。真实模型 Adapter 为后续选做，不阻塞 v1，不引入未确认 API/依赖。

在你拥有的 tests/system/ 补全真实 PostgreSQL/HTTP 流程测试：绑定/禁用 Agent、同 Task 多 Run、seed 与重试恢复、日志/统计可对账、105+ Span 分页及原型失败恢复回归。保留本轮已修复的 OpenAPI 原型路径子集断言，并加入 v1 路径/字段断言，不删除实质断言。复用 B 的 conftest，不另起会修改开发库的 fixture；缺接口只标阻塞不伪造通过。先交无绑定单元实现，B 第一批合入后完成绑定及全系统验证。执行后端测试脚本和 Ruff，在专用环境运行十万数据生成，提交 C.md 含 seed、配置、Task/Run ID/实际数量、测试结果/提交 SHA、遗留问题。仅提交自己的分支或 PR，由负责人集成。
```
