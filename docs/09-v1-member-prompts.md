# 三名成员独立开发 Prompt（解耦版）

分发前先合入公共基底解耦 PR；三人均从同一个 main 创建分支，无需等其他成员代码。v1 完整功能仍按 08；独立模块验收和负责人最终联调分开。

## 成员 A：前端

```text
你是成员 A，只修改 frontend/ 和 docs/deliveries/A.md，在 feature/v1-frontend 开发。先读 AGENTS、README 和 docs/ 全部文档，按 08 的 v1 完整页面清单实现；05 补充接口通则。你不是单独开发整个系统，不覆盖其他成员修改，不改后端和公共协议。

从共同 main 检查现有 Vue 基底，直接开始开发，不等待 B。使用 contracts/v1-http-examples.json 的冻结响应，构建你自己 frontend/ 内的显式 mock 层/Playwright 拦截；mock 不得启用于正式默认运行。所有接口字段、查询和状态按 05/08，样例只是形状示例，排序/过滤规则仍按文档。支持配置切换真实 API，mock 测试不冒充真实联调。

完成总览（含平均/P50/P95/Token/趋势/错误分布）、Agent 创建/编辑/启停、Task/Run 列表详情及同 Task 多次执行、选择 ACTIVE Agent 绑定、完整 Trace 树/相对时间线/详情/事件、全局日志筛选跳转、Agent/工具分析及两类实验的执行/前后计划/历史。保留原型成功/失败/查询重试；所有页面导航/刷新/空/加载/失败/分页可用；Trace 取完分页再构树；普通请求 15 秒、实验请求 150 秒。真实模型不在 v1 必做。

你拥有前端依赖与 lock、浏览器测试。独立验收：npm ci、npm test、npm run build，以及覆盖全部页面和边界的 mock 浏览器测试通过；明确区分 mock 套件和真实原型回归，不依赖 B 的新 API。可在已有原型后端上验证旧流程，不要求等 B 才交付。负责人集成后统一运行真实全站联调。A.md 列出功能编号/文件/真实命令结果/mock 状态/配置/提交 SHA/未完成项。公共契约疑问找负责人，不自行改接口；提交自己的分支或 PR，不自行合 main。
```

## 成员 B：业务 API、数据库和实验

```text
你是成员 B，在 feature/v1-backend 开发，只修改 08 分配给 B 的后端业务模块、数据库、后端依赖/lock、运行配置、tests/backend/ 等自有测试和 docs/deliveries/B.md。先读 AGENTS、README、docs/ 全部文档及现有代码，不能覆盖别人的修改，不改 frontend、C 的执行模块、公共 contracts 或根测试 fixture。

你可直接开始，不等待 C。app.contracts.execution 的 SimulationConfig（含 agent_ids）、app.contracts.trace 的 Span/Event/SimulationResult 已由负责人提供，直接复用，旧导入兼容保留。不要再建设或重定义这套协议。当前 services/runs.py 的 Agent 绑定临时 409 拒绝分支由你替换为创建 Run 前的存在/ACTIVE 校验和规范化传参，按 08 返回 404/409/422。配置 UUID 使用 model_dump(mode="json") 等方式传递字符串列表，C 函数签名不变。

完成 05/08 的全部业务 API：Agent 创建/查询/更新/启停、Task 查询和同 Task 多 Run、Run 列表筛选、Trace/事件、全局日志、完整统计（含 P50/P95、Agent Token、工具总耗时）、两种索引实验的隔离执行/前后测量/历史结果/超时和启用配置。保持原子事务、终态冲突、UTC、稳定分页、统一错误及 PATCH CORS。数据库不改已应用 001，新增迁移须经负责人审查。

独立测试使用真实 PostgreSQL *_test 库，自行构造 Agent、Task、Span/Event 数据；需要模拟器时可用现有原型，或在 tests/backend 中 monkeypatch runner.run_simulation 为合法固定 SimulationResult。不得让统计/事务测试依赖 C 未来随机输出，也不得通过变更 C 的代码使测试通过。新 fixture 放 tests/backend/conftest.py，不改根 conftest。实验数据自己隔离构造，不等待 C 的十万生成器。执行后端测试入口和 Ruff，不以 skipped/SQLite 替代数据库验收。完整响应与 contracts/v1-http-examples.json 的字段形状核对，数值必须来自真实查询。

B.md 记录 API 清单、功能编号、配置/迁移、命令结果、固定数据与真实数据库证据、提交 SHA/遗留项。独立模块可交付后由负责人合并三分支并验证真实 C/A 联调；你不承担跨成员代码合并。公共协议变更找负责人，不修改 app/contracts、公共样例、tests/system 或 C 模块。
```

## 成员 C：模拟执行、采集和数据生成

```text
你是成员 C，在 feature/v1-simulator 开发，只修改 recorder（除 contracts.py 兼容导出）、simulator、adapters、test_recorder.py、tests/simulator/、scripts（不改 test_backend.py）和 docs/deliveries/C.md。先读 AGENTS、README、docs/ 全部文档及现有实现。你不是整个后端负责人，不覆盖别人的修改，不改 B 的业务/API/数据库/依赖和公共模型。

你可以立即实现所有执行模块，不等待 B。从 app.contracts.execution 导入已经提供的 SimulationConfig（含 agent_ids），从 app.contracts.trace 导入公共结果模型。run_simulation(run_id,trace_id,config) 和 SimulationResult 保持不变；Recorder 不直接写数据库、不发 HTTP；纯模块测试传任意合法 UUID 即可，不要求测试前调用 Agent API。ID 的数据库存在/ACTIVE 验证属于 B，不在模拟器重复实现。

完成 research 模拟、按 agent_ids 顺序绑定各角色 AGENT 及其 LLM/TOOL、事件、成功/失败/最多一次恢复重试、seed 复现；根 WORKFLOW agent_id=null，无绑定旧请求保持兼容。重试占 Span 预算，严格维持根唯一/无环/完整父子关系和 500 Span/2000 Event 上限。所有时间 UTC，只有 LLM 记录 Token，独立 Recorder 不共享栈并发。真实模型仍为选做，不阻塞 v1。

按 08 第 7 节实现 scripts/generate_data.py 标准库 HTTP 工具，参数/default/退出码/实际落库数量摘要与契约一致；它只调用基底已有六个原型 API。无绑定模式可直接对本分支原型后端验证 200 Run × 500 Span 至少十万数据，不等待 B 的新 Agent API；有绑定参数的序列化可用你自己测试内的 HTTP 假服务验证，真正绑定全链路由负责人集成后验收。不要盲重试 POST、假报生成量或清空开发数据。

新独立测试放 tests/simulator/，必要局部 fixture 放该目录；覆盖绑定/继承、空绑定兼容、seed、失败/恢复、数量边界及生成器协议/错误处理。不再要求你在分支内验证 B 尚未实现的日志/统计/禁用 Agent API，也不改公共 tests/system 和根 fixture。执行模块测试、原型回归及 Ruff；C.md 提供功能编号、seed/配置、真实生成摘要、命令结果/提交 SHA、遗留项。提交分支或 PR 给负责人，负责人负责所有跨模块系统验收。
```
