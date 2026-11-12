# v1 正式版范围、协作边界和集成验收

状态：v1 目标及验收契约；集成实现与实际验证见 [12-v1-integration-verification.md](12-v1-integration-verification.md)。适用三名成员在同一原型上开发各自模块，再由负责人集成。v1 指本地单实例可运行的课程正式版，不代表生产级部署。

## 1. 唯一依据与基线

原型 PR #1 已于本轮审查前合并。共同代码基线为 origin/main 的 c310680（包含原型 bc32d37）；PR #2 也已合并；分发前负责人须将本轮公共基底解耦 PR 合入 main 并告知统一起点。所有人从更新后的 main 创建各自 feature 分支，不从早期只有目录的提交开发，不重建项目。

优先级：本文件对 v1 范围、补充参数及职责的明确规定 > 05 的其余 HTTP/事务规则 > 02 的五表 SQL > 03 的通用工程规范。01 为总体背景，06/07 为原型历史交付记录。任何剩余冲突先找负责人，成员不得各自改契约。数据库结构以 001 和后续经审查的迁移为准，不能照抄 01 的旧表字段。新增 API 以本文件和 05 为设计依据，B 的 OpenAPI 必须匹配；实现偏差不能以“OpenAPI 为准”擅自改变设计。

## 2. v1 必须交付的功能效果

| 编号 | 用户可见效果 | 交付人 |
|---|---|---|
| V01 | 创建、查询、修改 Agent 名称/角色/模型信息及启停状态 | A 页面，B API |
| V02 | 创建 Task、分页查看 Task，选择已有 Task 多次启动模拟 Run；分页筛选历史 Run | A/B |
| V03 | 显示 RUNNING 到终态的变化，跳转历史 Trace；刷新后可重新查询 | A/B/C |
| V04 | 完整调用树、相对时间线、Span 字段/耗时/Token/错误及 Event；大于 100 Span 不截断 | A/B/C |
| V05 | 跨 Trace 日志按 severity、task_id、agent_id、run_id 和时间筛选；点击定位 Trace | A/B |
| V06 | 总 Run、成功/失败数与率、平均耗时、Token、运行趋势、Agent/工具/错误分布 | A/B，C 提供关联数据 |
| V07 | 至少两种索引实验的真实前后耗时、执行计划、规模和策略；可执行并查看历史结果 | B 实验服务，A 页面 |
| V08 | 无模型密钥也能生成成功/失败及失败后恢复的模拟数据，支持 seed；生成至少 10 万 Span 的可复验工具 | C，B 提供现有服务 |
| V09 | 空库及现有原型库均可安装/迁移；测试独立库、统一错误、启动说明和成员交付记录 | 三人分别交付，负责人集成 |

v1 真实模型、OTLP/外部采集、外部 finish、取消任务、流式 Span、持久化任务队列、多进程部署、账户权限均不属于必做验收。REAL 保持 409 FEATURE_NOT_AVAILABLE，前端不显示可执行的真实模型按钮。C 可另开后续任务设计 Adapter，不能让其成为本次发布依赖。Task 编辑/删除、Agent 删除不在 v1 接口范围；通过 DISABLED 管理 Agent。C 仅需支持已约定 research 场景，不各自新增 scenario 枚举。

页面可合并布局，但以上功能全部可访问，不因历史文档“四页/五页”而遗漏。

## 3. 文件所有权（覆盖含糊范围）

| 成员 | 可以修改 | 不能自行修改 |
|---|---|---|
| A | frontend/（含 Vue 类型、API client、浏览器测试、依赖 lock） | backend/、数据库、根目录配置 |
| B | backend/app 中除 contracts、recorder、simulator、adapters 外的模块；backend/tests/test_database.py、test_cors.py 及新增 tests/backend/（可含局部 conftest.py）；database/；backend 的依赖/lock；根目录 Compose/.env.example | 公共 contracts、根 conftest、C 的模块/测试、frontend/ |
| C | backend/app/recorder（除 contracts.py 兼容导出）、simulator、adapters；backend/tests/test_recorder.py 及新增 tests/simulator/；scripts/（test_backend.py 入口冻结不动） | 公共 contracts、根 conftest、tests/system、B 的代码/依赖和数据库迁移、frontend/ |

docs/ 公共文档、README、AGENTS、backend/app/contracts/、recorder/contracts.py 兼容导出、contracts/ HTTP 样例、backend/tests/conftest.py、test_shared_contracts.py、tests/system/、scripts/test_backend.py 均由负责人维护并冻结；各成员仅可修改 docs/deliveries/A.md、B.md、C.md 各自交付记录。B/C 直接导入公共模型，不能各建一套或相互导入业务服务。B 新测试 fixture 放 tests/backend/conftest.py，C 新 fixture 放 tests/simulator/conftest.py；两者不能改根 fixture。根目录 .gitignore 等共享文件变更交负责人合并。

## 4. B/C 关联 Agent 的确切协议

v1 新增可选 `simulation_config.agent_ids: list[UUID] | null = null`（现已由负责人在 app.contracts.execution.SimulationConfig 提供，无需等 B 修改 Schema）。长度须等于 agent_count、去重且全部存在并为 ACTIVE，格式或长度错误 422；不存在的 ID 返回 404；DISABLED 返回 409 CONFLICT。该约束在创建 Run 前校验，失败不创建 Run。

省略/null 时保持原型无绑定模式 agent_id=null，保证旧请求兼容；前端正式演示应先创建并选择 Agent，再传入 ID。C 不查数据库：按列表顺序绑定 Research/Analysis/Review 的 AGENT Span，同一角色下 LLM/TOOL Span 及其事件关联使用同一个 agent_id，WORKFLOW 根仍为 null。Span 数不够时只采用可容纳的前若干角色。TOOL 操作应放在对应 AGENT 节点下；保证 min/max 是总 Span 数（包括根和角色）。无绑定测试仍可单独运行。

公共基底提供 agent_ids 类型/数量/去重校验；v1 的 HTTP 绑定执行已实现数据库身份校验和模拟器传递，具体验证见 12。B 在创建 Run 时校验 Agent，向 run_simulation 传标准化 config（UUID 序列化为字符串）；持久化前仍校验五表约束。Run 开始后 Agent 被禁用不追溯使该 Run 无效，绑定的是启动时快照身份，Agent API 不提供删除。

`run_simulation`、`SimulationResult`、`complete_run` 签名沿用 05，不新增外部写入接口。失败恢复的模拟用不增加配置字段的约定：failure_rate=1 为未恢复业务失败，0 为成功；0<failure_rate<1 的失败操作最多重试一次（生成新 Span 并记录 retry_count=1），重试成功允许 Run SUCCESS 且 error_count>0。重试占总 Span 预算，没有预算则失败；每个 Run 最多 500/2000，不能为重试突破上限。seed 决定结构/结果，不决定 ID/时间。C 为固定 seed 的恢复场景写测试，交付演示 seed 及配置。

## 5. HTTP 补充与边界

全部基础路径 /api/v1，05 已列举的接口都是 v1 必做；没有另行授权的旧 /api/runs/simulate 等别名不实现。POST Agent 仅接受 name/role/provider/model_name，status 初始 ACTIVE；name/role 含非空白字符，长度按 SQL，provider/model_name 可省略或 null。PATCH 的 name/role/status 不允许 null，provider/model_name 可用 null 清空；空对象及未知字段 422。Task/Run/Agent 资源字段、列表排序和分页见 05。查询 page 超出末页返回空 data，total 不变。可选筛选省略表示不限制，非法枚举/ID/时间/未知查询参数返回 422；不要给查询参数也设置 extra=forbid 后忘记列入分页字段。

GET /tasks 无额外搜索参数；GET /agents 增加可选 status=ACTIVE|DISABLED（A 用于选择执行 Agent）。Run 筛选只用 05 的 task_id/status/source_type/start_time/end_time。可选时间边界可单独出现，若同时出现 start>=end 则 422，必须带时区并归一 UTC。from/to 同理。数据超出时间窗口不进入计数。事件列表空筛选结果 200，错误资源路径 404。Trace 局部 events 的 span_id 仅作过滤，不存在的 Span 返回空列表。

GET /analytics/overview 的 data 固定包含 total_runs、success_runs、failed_runs、success_rate、avg_duration_ms、total_input_tokens、total_output_tokens、total_spans；v1 额外增加 p50_duration_ms、p95_duration_ms（对有 ended_at 的 Run 耗时用 PostgreSQL percentile_cont 连续分位数，空集 null）。失败率前端按 1-success_rate 计算，分母为 SUCCESS+FAILED；零分母 null 显示“—”。总 Run 包含其他状态，不把总 Run 显示为总 Task。Token sum 空集为 0（这是合计，不代表未知 Span 的 Token 已知）；平均耗时单位 ms。Agent/工具错误率由 error_count/span_count 在前端派生，避免各自新增字段。Agent 性能表按 05 的 span_count 降序，其平均值只统计 AGENT Span；不能用子 LLM 的耗时/Token 重复累计。v1 在 /analytics/agents 各行额外返回 total_input_tokens、total_output_tokens（同一 agent_id 的 LLM Span 求和，空集 0），并在 /analytics/tools 各行额外返回 total_duration_ms（TOOL Span 耗时之和）。这些是 B 明确要交付的新增字段，A 不自行推测。

趋势 UTC 日期、缺失日期补零、所有统计窗口按 Run.started_at 过滤，事件窗口按 occurred_at；GET /events 在 05 的筛选外补充 trace_id（32 位小写 hex）、error_type（匹配关联 Span.error_type，最长 100）、start_time/end_time 不作为别名，统一用 from/to；trace_id 格式合法但无匹配记录返回空列表。日期控件先将用户时区边界转为 UTC。POST 创建 201、Run 202、PATCH/查询 200；统一 error 和 nullable 响应。本轮已将原型测试中 OpenAPI 路径数恰好为 7 的断言改为要求原型路径子集，C 后续保留该回归检查并添加 v1 路径断言。CORS 必须支持 PATCH，当前审查已修复。

### 页面与交互完整验收清单

- 总览：total_runs、success_runs、failed_runs、成功/失败率、平均/P50/P95 耗时、Token 输入/输出、总 Span、日期趋势和异常分布；空值显示“—”，日期窗口可清空恢复全量；不把非终态当失败。
- Agent：创建/查看/编辑/启停，分页与状态筛选，展示 provider/model_name；失败输入显示后端错误，编辑不覆盖未修改字段。
- Task/Run：创建 Task、列表及详情、同一 Task 多次执行、选择 1–3 个 ACTIVE Agent；配置 agent_count/Span 范围/failure_rate/seed；Run 按任务/状态/来源/时间分页，查看并跳转 trace_id。没有 ACTIVE Agent 时提示创建，也保留不绑定执行的兼容路径。请求尚未接受前禁重复提交，断网后允许按 Run ID 查询。
- Trace：从历史列表或输入 Run ID 打开；状态/起止时间/Span/错误数量；调用树与相对时间线（时间线以最早 start_time 为零，宽度为 end-start，不把父子耗时相加作为总时长）；节点联动详情和该 Span Event，Token、attributes、错误和模型/工具字段完整可见；过滤展示不能破坏完整原始树。RUNNING、零 Span FAILED、加载失败均有明确状态。
- 日志：severity/task_id/agent_id/run_id/trace_id/error_type/from/to 筛选及清空，分页、按 05 排序；显示时间/等级/消息及相关标识，点击进入关联 Trace。
- 性能：Agent/工具表，展示调用次数、错误数/率、平均耗时及前述 Token/工具总耗时；明确数值统计单位及分组口径，可选时间窗口；错误分布空数据不绘制虚假图表。
- 实验：两个预定义案例、三个规模，执行加载/失败/超时状态、历史分页；展示前后耗时/计划/实际规模/策略，可派生加速比（before/after，after 为 0 显示“—”）；结果不必总是提升。历史结果必须刷新或重启后仍可见。
- 所有页面：可达的导航、浏览器刷新和直接访问路由有效、加载/空/失败/重试/分页；时间统一展示用户本地并明确时区；前后端真实联调。A 可统一采用 Vue Router 的 hash 模式，减少静态托管刷新配置要求；UI 库是否采用依设计可自行实现，功能验收不依赖截图风格。

## 6. 实验服务冻结

为避免 A 等待 B 自定格式，v1 固定两个 case_code：TRACE_QUERY_INDEX（按 run_id/start_time 查询）和 ERROR_PARTIAL_INDEX（status=ERROR 的时间查询）；dataset_size 只接受 1000、10000、100000，表示实验中的 Span 行数。B 构造合法可复现数据到单独连接的 TEMP 表或专用隔离实验库，不能删除/修改业务库索引或清空业务数据；每种规模真实测量，不预设加速比例。已有 001 中已建的业务索引不得被“无索引实验”移除。

POST /benchmarks/run 接受 {case_code,dataset_size}；同步执行，201 返回 05 单个结果对象。duration_ms 表示有索引方案的耗时；index_strategy 为 no_index_vs_run_start 或 no_index_vs_error_partial。plan 固定为对象：{before: object, after: object, duration_before_ms: number, duration_after_ms: number, repeats: integer}，before/after 为 EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) 顶层数组首个对象；repeats=3，耗时取三次 Execution Time 的中位数；plan 保存对应中位数一次的对象，分别明确实际测量。索引创建耗时不混入查询耗时。result_id/created_at/dataset_size 等字段仍按 05。

结果存于忽略提交的 backend/var/benchmarks.json，B 负责进程内写入锁与临时文件原子替换；GET /benchmarks/results 使用该文件，缺失文件返回空列表，损坏文件报 500 而不静默丢历史。实验并发请求返回 409 CONFLICT。失败不追加半个结果，SQL 超时返回 504 BENCHMARK_TIMEOUT（统一 error 格式），加到 OpenAPI。B 设置整次实验上限 120 秒并使用 SQL 超时/取消保证清理；A 对该接口用 150 秒超时，不沿用普通接口 15 秒，并展示加载状态和耗时 ms。BENCHMARK_ENABLED 默认 false，disabled 时 POST 返回 409 FEATURE_NOT_AVAILABLE；B 在模板补充此变量，负责人本地验收显式启用，GET 仍可读历史。

## 7. 数据生成及实验依赖

C 提供 scripts/generate_data.py 命令，参数 --base-url（默认 http://127.0.0.1:8000/api/v1）、--runs（默认 200）、--spans-per-run（默认 500）、--seed（默认 42）、--agent-ids（可选逗号分隔 UUID）。创建一个 Task，多次启动并轮询到终态；配置 min=max=spans-per-run，ID 列表给定时 agent_count 等于列表长度。串行或有界并发，错误有限重试且失败退出非零；不要重试 POST 导致悄悄创建重复 Run，查询可安全重试。按 Trace 概览累计实际落库 Span，输出 Task ID、Run 数、成功/失败数、实际 Span 数与参数；10 万规模不要放入默认单元测试。失败 Run 如含完整 Trace 仍计实际 Span；零 Span 故障导致最终数量不足则报错。

数据生成通过 HTTP API，不导入 services，不新增 Python 依赖；使用标准库 urllib。B 的索引实验独立构造实验数据，因此其功能开发不等待 C 先生成业务库十万数据。业务数据库大规模查询检查使用 C 的生成器另行验收。

## 8. 独立开发、负责人集成和发布门槛

1. 负责人先合入本轮公共基底，三人从同一 main 分别创建 feature/v1-frontend、feature/v1-backend、feature/v1-simulator。A/B/C 均无“等待其他成员第一批代码”的任务。
2. A 使用冻结的 contracts/v1-http-examples.json 做 mock 页面和浏览器测试；B 使用本分支原型模拟器或在 B 自有测试中替换 runner.run_simulation 返回固定 SimulationResult，以真实 PostgreSQL 验证事务、Agent 身份和统计；C 使用任意合法 UUID 作为纯模块输入测试绑定/继承/重试，测试不要求这些 UUID 已在数据库中（数据库验证归 B）。公共模型已经就绪，所有人可同时启动。
3. A 的独立交付条件是页面、冻结样例上的 mock 测试、测试/构建通过并可配置切换真实服务；B 是 API/数据库/实验及自己的固定数据测试通过；C 是采集/模拟器/生成器及独立测试通过。mock 必须显式标识为模拟测试，不宣称真实后端已联调。C 的无绑定十万数据生成可以在本分支已有六个原型 API 上独立验证，无须 B 新 API。
4. 负责人接收三个分支后统一汇总；不要求成员互相 cherry-pick 或等待上游代码。先分别审查，再在集成分支合并三者，运行公共 tests/system 和三套模块测试，执行真实前后端、Agent 绑定、统计对账、实验及大规模数据的联合验收。出现契约偏差由对应模块修复；真实联调失败不能以 mock 成功代替。
5. tests/system/ 的 v1 跨模块测试由负责人负责扩展；C 不再承担必须等 B API 的日志/统计/禁用 Agent 系统测试，A 不被要求在 B 开发完成前提供真实全站浏览器验收。独立模块完成和 v1 整体验收分开记录，完整 v1 仍必须真机通过所有功能。
6. 发布前：干净目录安装 lock、空库迁移/已有原型库升级、独立库后端全量（不允许集成测试 skip）、前端测试/构建、真实 API 浏览器验收、checksum、PATCH CORS、身份绑定、统计对账，全部通过。公共基底/模型或依赖新增需求交负责人统一处理，成员不能以解耦名义修改现有契约。

最终演示：创建三个 ACTIVE Agent → 创建 Task → 绑定运行成功与失败各一次 → 从 Run 列表重开 Trace → 完整树与时间线 → 筛选日志定位 Trace → 按窗口核对统计与 Agent 关联 → 两项实验前后计划 → 重启仍能查询历史。另以固定 seed 演示恢复成功且存在 ERROR Span；生成器实际累计至少 100000 Span。所有字段、计数、分页边界和错误格式需有自动化测试。用专用测试库测试崩溃/恢复，不能重启正在执行别的任务的共享后端。

交付记录 docs/deliveries/{A|B|C}.md 必须列：基线、提交 SHA、修改文件、需求编号对应功能、真实命令/结果、mock 与真实服务区别、未实现内容、负责人需执行的配置/迁移步骤。独立前端可带明确 mock 验证记录交付；存在待接接口或跳过的必要数据库测试时，负责人不得标为正式版已完成。v1 发布需由负责人执行以上门槛，本次审查只确认开发边界和当前基底，不承诺未实现代码没有缺陷。
