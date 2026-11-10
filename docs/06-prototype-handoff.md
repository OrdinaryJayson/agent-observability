# 原型交接与迭代计划

版本 0.1.0，公共边界以 [开发与联调契约](05-integration-contract.md) 为准。本文件说明实际交付和待办，不将计划功能当作已实现。

## 1. 已实现功能与代码入口

| 功能 | 入口 | 实际行为 |
|---|---|---|
| 配置和数据库 | backend/app/core/、根目录 Compose | 根目录 .env、进程变量优先、CORS、连接池和 UTC；独立 PostgreSQL 16 |
| 五张业务表及核心索引 | database/migrations/001_init.sql | 采用 02 完整建表 SQL 和第一阶段索引，没有改名公共字段 |
| 迁移 | backend/app/migrate.py | 顺序执行、迁移记录、checksum 和事务锁；重复执行不重复建表 |
| 任务及执行 | api/routes.py、services/runs.py | 创建 Task、202 接受 Run、BackgroundTasks 执行、状态查询 |
| Recorder | recorder/recorder.py | 上下文 Span、父子关系、Event、异常收尾；仅内存采集 |
| 模拟器 | simulator/runner.py | research、seed、数量和失败率；最多三种模拟角色；无模型调用 |
| 事务及校验 | services/run_completion.py | Run 行锁、终态冲突、树/事件/规模/Token 校验、一次提交或全部回滚 |
| 查询 | repositories/execution.py | Run/Trace 查询、Span/Event 分页、Event 按 span_id 筛选、稳定排序 |
| 故障恢复 | services/runs.py、main.py | 回滚后另行标 FAILED，启动恢复遗留 Run；错误不回显原始请求和内部异常 |
| 前端 | frontend/src/ | 创建执行、2 秒轮询、15 秒单请求超时、失效请求取消、Run ID 恢复、树/详情/事件 |
| 测试 | backend/tests/、frontend/src/ 的测试、frontend/tests/ | 校验、事务/并发、API、分页、恢复、浏览器成功/失败/查询重试 |

六个原型 API 及 /health 已实现，参数和响应在运行中的 /docs 可查。其他第一版接口尚不存在，前端不得提前调用未交付路由。

## 2. 成员后续待办

### A：前端

- [ ] 在 api/client.ts、types/index.ts 上增加 Agent、Task、Run 列表，和 B 协调交付顺序。
- [ ] 拆分 App.vue 为页面/组件，接入路由；新增管理页、时间线、全局日志及性能分析。
- [ ] 对应页面需要时再引入 Element Plus/ECharts。
- [ ] 保留全部分页、加载/空/错误状态；新增页面补充联调测试。

验收：当前原型流程不回退，调用已交付 API，树不截断，统计数值遵循契约。

### B：后端与数据库

- [ ] 实现 Agent 管理、Task 查询、Run 列表及筛选。
- [ ] 实现 overview/agents/tools/errors/trend 统计，覆盖空集、时间边界与分母口径。
- [ ] 实现跨 Trace 全局事件查询，保留现有局部事件查询兼容性。
- [ ] 开展至少两项可复现数据库实验，再交付实验结果接口；记录真实数据和计划。
- [ ] 维护依赖、迁移、OpenAPI 和集成测试；扩展时保留 complete_run 原子性。

验收：接口符合 05，空库/已有版本均可迁移，现有数据库测试通过，公共字段变更由负责人确认。

### C：模拟器、采集与系统测试

- [ ] 扩展场景和事件；与 B 对接 Agent 管理后再绑定真实 agent_id。
- [ ] 增加失败后恢复成功的模拟流程，当前失败模式直接导致 Run FAILED。
- [ ] 通过统一服务生成跨多个 Run 的十万级 Span 数据，保持单 Run 500/2000 限制。
- [ ] 实现 adapters/ 真实模型适配，和 B 协调 REAL 入口、配置、错误处理。
- [ ] 补测长任务、最大规模及数据库中断等系统场景，记录命令和实际结果。

验收：不直接写数据库，seed 重现结构和随机结果，凭据仅来自后端，模拟路径不依赖模型配置。

### 负责人

- [ ] 按 README 启动并复核原型后分发任务，协调 A/B 接口交付时间。
- [ ] 审查公共契约和跨成员文件变更，要求合并前测试、构建和相关浏览器流程通过。
- [ ] 原型与完整系统分别验收，后续按 01/05 补齐正式功能。

## 3. 扩展注意事项

1. 数据库 SQL 是结构来源，models/tables.py 以 SQLAlchemy Core 反射迁移后的表；运行期不自动建表。新增迁移并执行 python -m app.migrate 后重启后端。不要修改已应用的 001，新增 002 等文件。schema_migrations 是技术记录表，不是新增业务表；未来 ORM 映射需与迁移一致。
2. B 的 execute_run 调用 C 的 run_simulation，再调用 complete_run；Recorder 不拥有数据库会话，不执行 commit 或 HTTP 写入。公共签名和字段名保持 05 一致。
3. Run/Trace ID 由 B 创建，Span/Event ID 由 Recorder 创建。当前 agent_id 均为 null，角色名称仅用于展示；agents 表已建但管理功能待开发。
4. 完整 Trace 与 Run 终态单事务提交；失败回滚后可单独标 FAILED。终态不可追加，内部重复完成返回冲突。外部采集、finish 和外部重试幂等尚未实现。
5. 当前只允许一个后端实例/worker：启动恢复会将遗留 RUNNING 标 FAILED。运行任务时避免热重载；BackgroundTasks 没有持久化调度、取消或自动重试保证，多实例需单独设计。
6. UTC/TIMESTAMPTZ；耗时由时间差派生；只有 LLM Span 记录 Token，未知为 null。模拟 Token 是测试数据，不代表真实模型性能；seed 不固定 UUID、时间或耗时。
7. Span/Event 均须完整分页；RUNNING 期间可能零 Span；FAILED 且零 Span 是基础设施故障允许的结果，页面显示 error_summary。
8. 后端根目录 .env、进程变量优先；前端只读 VITE_API_BASE_URL。POSTGRES_PORT 为可选端口覆盖，默认仍 5432。修改已有卷的环境变量不会自动修改数据库账号/密码，应显式管理已有数据库。
9. 后端测试清空独立 *_test 库中的业务表，禁止指向真实数据；浏览器测试向本地开发库写少量模拟任务。不提交配置秘密、数据库卷、日志和测试截图。
10. 成员交付时说明文件、功能、测试和遗留问题；公共契约变更须同步调用方与测试，按功能分支审查合并。

## 4. 当前限制

- 每次启动创建一个新 Task，无历史列表；查询重试不创建新 Run，可用已有 Run ID 恢复。
- 原型用原生 Vue 组件/CSS，尚无图表库和完整 UI 系统。
- 模拟器按数量生成根/角色/操作；Span 数量较少时只生成能容纳的角色，agent_count 表示最多角色数。
- Recorder 每个 Run 独立实例，当前用于顺序执行；未来并行 Agent 需先将父节点上下文改为任务隔离并补并发测试，不能共享现有栈。
- 后台日志仅记录 Run ID 和简短失败阶段；结构化日志、认证及部署能力留待正式系统设计。
- /health 检查数据库连通，完整就绪需迁移成功和端到端验收。
- 修改直接依赖文件后应更新 lock；安装使用 lock，以便队员复现环境。
