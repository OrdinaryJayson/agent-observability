# 开发与联调契约 V1.0

> v1 正式开发入口：[08 范围与集成契约](08-v1-release-contract.md)。其明确补充覆盖本文件的历史范围与含糊约定；已实现功能仍以代码及 06/07 的交付记录区分。

本文件是项目负责人确认的实施契约，覆盖原型至第一版。与 01、02、03 的历史示例有冲突时，以本文件为准；数据库表定义仍以 02 的五表 SQL 为准。变更公共契约前须由负责人确认，并同步本文件、调用方、测试及 OpenAPI。现阶段这是设计约定，不代表代码已经实现。

## 1. 实施范围和依赖

先交付原型：创建 Task → 创建并异步执行模拟 Run → 原子持久化 → 查询 Run、Trace、全部 Span 和 Event → 前端展示。原型不依赖真实模型、统计或性能实验。原型通过后完成本文件的第一版接口、管理页面、日志与统计、至少两项数据库实验。真实模型 Adapter 为后续扩展；没有模型配置时模拟流程仍可独立运行。外部 Span 批量写入和 `/runs/{run_id}/finish` 不属于第一版，不实现；02 中相关设计保留为未来方案，不得由客户端绕过内部完成事务。

## 2. 所有权和集成边界

| 范围 | 负责人 | 交付/依赖 |
|---|---|---|
| frontend/ | A | 页面、类型、API 客户端及前端测试；调用本文件 HTTP 契约 |
| backend/app/api、schemas、models、repositories、services、core、main.py 和 backend/tests 中后端测试；database/；根目录运行配置 | B | 数据库、HTTP、调度和 complete_run；与 C 共同确认调用签名 |
| backend/app/recorder、simulator、adapters；scripts/；系统测试 | C | Recorder、模拟器、数据生成及端到端测试；不直接提交数据库 |
| docs/ 和公共契约 | 项目负责人 | 审查、设计变更、集成及验收 |

共享文件由负责人指定主负责者；跨边界变更先取得对应成员明确授权。C 的系统测试放 `backend/tests/system/`，该子目录由 C 负责；其他后端测试由 B 负责。B 创建 Python 项目及依赖，C 提出依赖需求，由 B 合并；A 负责前端依赖。所有路径从仓库根目录计算。

## 3. 运行与配置约定

采用 03 第 2 章的版本范围：Python 3.11、PostgreSQL 16、Node.js 22、Vue 3、FastAPI 0.115、SQLAlchemy 2、Pydantic 2。B 提交 `backend/requirements.txt` 和可重复安装的确定版本；A 提交 `frontend/package.json` 与 lock 文件，使用 `npm ci`。B 负责根目录 `docker-compose.yml`、`.env.example` 和迁移执行说明。Compose 的 db 仅负责 PostgreSQL，前后端本地运行；不得提交真实凭据。数据库配置采用 03 的变量名；`.env` 放仓库根目录，后端从仓库根目录 `.env` 加载，进程环境变量优先。前端使用 `frontend/.env.local` 的 `VITE_API_BASE_URL`，其示例由 A 提供；该文件不得提交。

B 提供可重复执行的迁移入口和迁移记录，空库按顺序执行 `database/migrations/` 的 SQL；已初始化数据库不得依赖 Docker 初始化目录自动执行新增迁移。运行步骤、健康检查及测试命令由各负责人随代码更新 README。默认端口依 03：DB 5432、API 8000、前端 5173，后端 CORS 允许本地前端。测试使用独立数据库，不得清空开发数据库。

## 4. 共同数据与执行协议

数据库约束、UUID、trace_id、span_id、UTC、状态和 Token 规则以 02 SQL 和 03 第 5 章为准。Run 创建时由 B 的服务生成 run_id 与 trace_id，并传给 C；C 只生成 span_id 和 event_id，不重新生成 trace_id。一个 Run 一条 Trace；最终 Trace 恰有一个根、无环、所有节点可达根、父 Span 属于同一 Run；Span/Event 必须满足 02 表约束。单 Run 最多 500 Span、2000 Event。空白 trace 和缺少根节点不能作为成功 Trace 完成。

### B / C Python 调用契约

B 负责调度；C 提供 `backend/app/simulator/runner.py` 中同步函数：

```python
run_simulation(*, run_id: str, trace_id: str, config: dict) -> SimulationResult
```

C 在 `backend/app/recorder/contracts.py` 提供 `SimulationResult` 数据类型：`spans: list[dict]`、`events: list[dict]`、`final_status: str`（SUCCESS 或 FAILED）、`error_summary: str | None`。其中 Span/Event 的键和类型严格采用 02 第 2.5 节批量请求示例及 SQL 字段，所有可空字段显式提供 null；Event 不含 run_id，Span 不含 run_id，B 从调用参数补充。时间值为带 UTC 时区的 Python datetime，ID 为上述字符串形式，attributes 为 JSON 对象。B 不修改 C 的结果；由 B 先校验再持久化。`config` 允许 `scenario`、`agent_count`、`min_spans`、`max_spans`、`failure_rate`、`seed`；原型默认分别为 `research`、3、8、20、0.1、42。只支持 research；agent_count 为 1–3，Span 上下限为 1–500 且 min 不大于 max，failure_rate 为 0–1，seed 为整数。固定 seed 固定事件结构和随机结果，不要求 UUID 和时间相同。模拟器不得假造数据库中不存在的 agent_id；未关联真实 Agent 时使用 null。

B 在 `backend/app/services/run_completion.py` 提供：

```python
complete_run(*, run_id: str, spans: list[dict], events: list[dict],
             final_status: str, error_summary: str | None) -> None
```

B 自行管理数据库会话和事务：锁定 Run；确认 RUNNING；校验完整树、Event 引用及限制；插入所有 Span 和 Event；更新终态、ended_at、error_summary；一次提交。任一环节失败全部回滚。B 后台任务依次调用 C 的函数和该服务，不让 C 操作数据库或发 HTTP 写入。业务失败但生成完整 Trace 时以 FAILED 和完整 Trace 原子完成；未能生成可用 Trace 或完成事务失败时，B 在回滚后通过独立事务将仍为 RUNNING 的 Run 标为 FAILED，记录简短错误摘要，该情况下允许没有 Trace 数据。若数据库不可用无法标记，则由重启恢复处理。后端启动时将遗留 RUNNING Run 标为 FAILED 并设置 ended_at 和 03 指定错误摘要；该策略仅支持单后端实例。C 的未捕获异常由 B 按上述失败路径处理，不记录凭据。

同一 Run 不允许并发完成；完成服务对已终态 Run 返回冲突，不能再写入。该内部事务不使用静默 `ON CONFLICT DO NOTHING` 掩盖不同内容；任何唯一键冲突回滚。由于外部重试写入接口不在第一版，02 的批量接口重试和 03 的逐条幂等规则暂不适用，不应宣称已实现外部采集幂等。

## 5. HTTP 公共规则

基础地址 `/api/v1`，JSON UTF-8，snake_case，UTC ISO 8601。成功对象 `{"data": ..., "message": "success"}`，异步创建 Run 的 message 为 `run accepted`；列表为 `{"data": [...], "meta": {"page": 1, "page_size": 20, "total": 0}}`。错误为 `{"error":{"code":"...","message":"...","details":{}}}`，包括框架参数验证异常；禁止把 FastAPI 默认错误体直接作为公开契约。状态码按 03 第 7.3 节；错误码至少提供 VALIDATION_ERROR、RESOURCE_NOT_FOUND、CONFLICT、INTERNAL_ERROR。未知资源返回 404，非法请求参数 422，业务状态冲突 409。服务端 500 不暴露内部堆栈。所有列表 page 从 1 开始，page_size 默认 20、最大 100，非法值返回 422；total 为筛选后总数。所有 ID 路径非法格式返回 422。数据库排序必须有稳定的 ID 次级排序。各列表均返回完整资源字段，不依赖数据库列顺序。

资源字段：Agent 为 agent_id、name、role、provider、model_name、status、created_at；Task 为 task_id、title、description、scenario_type、created_at；Run 为 run_id、task_id、trace_id、source_type、status、started_at、ended_at、error_summary、created_at。Span 为 02 批量示例中的全部字段及计算值 duration_ms（毫秒，数字），不暴露 span_pk；Event 为 event_id、span_id、event_name、severity、message、occurred_at、attributes。字段类型与 02 表一致，nullable 数据返回 null，时间均输出 UTC；不向前端暴露数据库连接信息。

### 原型必做接口

| 方法和路径 | 请求与响应 |
|---|---|
| POST /tasks | body `{"title":"...","description":null,"scenario_type":"GENERAL"}`；title 必填，其他字段可省略并使用数据库默认/空值；201，data 为 Task。 |
| POST /tasks/{task_id}/runs | 02 第 2.4 节的 SIMULATED 请求；simulation_config 可省略，按第 4 节默认补全。任务不存在 404，参数非法 422；创建 RUNNING Run 后返回 202，data 含 run_id、trace_id、source_type、status。REAL 尚未启用时返回 409，code 为 FEATURE_NOT_AVAILABLE。 |
| GET /runs/{run_id} | 200，data 为 Run。终态通过 status 判断；RUNNING 期间不保证有任何 Span。 |
| GET /traces/{trace_id} | 200，data 包含 02 的 trace_id、run_id、task_id、status、source_type、span_count、error_count、started_at、ended_at；error_count 为 ERROR Span 数量。Trace 对应 Run 不存在为 404；无 Span 的已存在 Run 返回计数 0。 |
| GET /traces/{trace_id}/spans | 标准分页列表，返回扁平 Span；按 start_time、span_id 升序。前端依 total 逐页取完，再构建树；最多 500 条。 |
| GET /traces/{trace_id}/events | 标准分页列表，返回 Event；按 occurred_at、event_id 升序。未知 Trace 为 404；可选 `span_id` 筛选。 |

示例：`GET /api/v1/traces/{trace_id}/spans?page=1&page_size=100` 返回 `{"data":[{"span_id":"0000000000000001","parent_span_id":null,"agent_id":null,"operation_type":"WORKFLOW","span_name":"Task Execution","status":"SUCCESS","start_time":"2026-01-01T00:00:00Z","end_time":"2026-01-01T00:00:01Z","provider":null,"model_name":null,"tool_name":null,"input_tokens":null,"output_tokens":null,"error_type":null,"error_message":null,"attributes":{},"duration_ms":1000}],"meta":{"page":1,"page_size":100,"total":1}}`。

前端创建 Run 后每 2 秒轮询一次，终态停止；离开页面停止；请求失败显示错误并允许重试。终态后获取 Trace 和全部 Span/Event。FAILED 且 span_count 为 0 时显示 error_summary，不当作树构建错误。后台重启可能导致内存中未提交数据丢失，这是本版限制。

### 第一版其余接口

- `GET /agents`、`GET /tasks`：标准分页，按 created_at 降序、对应 ID 升序。`POST /agents` 按 02 示例，name、role 必填，provider、model_name 可空，201 返回完整 Agent。`GET /agents/{agent_id}`、`GET /tasks/{task_id}` 返回对应资源。`PATCH /agents/{agent_id}` 接受 name、role、provider、model_name、status 的部分字段；status 为 ACTIVE 或 DISABLED；空对象或未知字段 422，200 返回完整 Agent。
- `GET /runs`：支持 02 列出的 task_id、status、source_type、start_time、end_time、page、page_size；按 started_at 降序、run_id 升序。时间窗口作用于 started_at，左闭右开；缺省边界不限制。
- `GET /analytics/overview`：可选 `from`、`to`，按 Run.started_at 左闭右开；返回 02 示例字段。total_runs 包含所有状态，success_runs 和 failed_runs 分别只计 SUCCESS、FAILED；success_rate 的分母为 success_runs + failed_runs，分母为 0 返回 null。平均耗时只包括有 ended_at 的 Run，单位毫秒，空集 null；Token 将关联 LLM Span 的非空值求和，空集为 0；total_spans 统计这些 Run 的全部 Span。
- `GET /analytics/agents`：相同时间筛选，标准分页；以有 agent_id 的 AGENT Span 分组，返回 `agent_id`、`name`、`span_count`、`error_count`、`avg_duration_ms`；按 span_count 降序、agent_id 升序。仅统计非空已关联 Agent，error_count 为 ERROR Span 数。
- `GET /analytics/tools`：相同时间筛选，标准分页；按 TOOL Span 的 tool_name 分组，返回 `tool_name`（可为 null）、`span_count`、`error_count`、`avg_duration_ms`；按 span_count 降序、tool_name 升序，null 排最后。
- `GET /analytics/errors`：相同时间筛选，标准分页；对 ERROR Span 按 error_type 分组，返回 `error_type`（可为 null）、`count`；按 count 降序、error_type 升序，null 排最后。三个分析接口按所属 Run.started_at 筛选。空分组返回空列表。统计对象中的 name 从 agents 表读取。
- `GET /events`：跨 Trace 日志查询，标准分页；可选 `severity`、`task_id`、`agent_id`、`run_id`、`from`、`to`，时间范围作用于 occurred_at，左闭右开；通过所属 Span 和 Run 关联过滤。返回 Event 的全部字段及 run_id、trace_id、task_id、agent_id；按 occurred_at 降序、event_id 升序。
- `GET /analytics/trend`：支持上述 from、to，按 UTC 日期对 Run.started_at 分组，标准分页；返回 `date`（YYYY-MM-DD）、`total_runs`、`success_runs`、`failed_runs`，按日期升序；无数据日期不返回，由前端补零。异常分布使用 `/analytics/errors`。
- `GET /benchmarks/results`：标准分页，返回已完成实验结果，按 created_at 降序、result_id 升序。`POST /benchmarks/run` 接受 02 示例字段 `case_code`、`dataset_size`，只接受 B 在服务端预定义并文档化的案例和规模，非法值 422；201 返回结果。结果字段为 `result_id`（UUID 字符串）、`case_code`、`dataset_size`、`index_strategy`（字符串）、`duration_ms`（数字）、`plan`（JSON 对象）、`created_at`（UTC）。B 以服务端 JSON 文件持久保存结果，并明确文件路径和权限；不得新增业务表或接受任意 SQL。该接口同步执行，前端显示运行状态；基准实验仅限开发环境，不能与真实负载混用。

上述分析列表的 page、page_size 和 total 使用公共规则，avg_duration_ms 为算术平均值。`from`、`to` 均为带时区 ISO 8601 时间；from 不早于 to 时返回 422。输入验证细节以字段约束和本文件为准，OpenAPI 和实际行为必须一致。

## 6. 协作与验收

1. 负责人发布本文件并确认三名成员职责。B 先提交接口类型和初始化骨架；C 与 B 对第 4 节进行导入和类型联调；A 可按第 5 节样例使用本地 mock，并在 B 提供服务后替换为真实请求。模拟器可以与 B 的骨架并行开发，但共同接口不得各自改名。
2. 原型验收使用独立空测试库：执行迁移、启动服务与前端；创建 Task 和 Run；检查 202、轮询终态、数据库记录、Trace、分页完整性和前端树。至少覆盖成功、业务失败有完整 Trace、模拟器异常无 Trace、重复完成冲突、事务中途失败全回滚、超过 100 Span 的分页，以及非法父子关系和大小限制。
3. 第一版补测 API 参数和错误体、空统计与状态分母、时间区间边界、前端空/错误状态、数据库实验可复现性。C 保留运行命令、输入、实际结果和失败日志；负责人审查 A、B、C 的集成结果。真实模型未配置时不得阻塞模拟验收。
4. 每名成员提交实现说明、修改文件、测试命令及结果和遗留问题；公共契约变更由负责人审查并同步调用方及测试。禁止用模拟数据冒充真实性能实验结果。
