# 成员 B：业务 API、数据库和索引实验交付记录

日期：2026-11-10（Asia/Shanghai）。本记录区分 B 模块验证与负责人最终三方集成验收。

## 基线与状态

- 分支：`feature/v1-backend`。
- 共同基线：`1d7c606`（公共契约解耦 PR #3 合并提交）。
- 实现提交 SHA：`21e951d740f3019db9cc5f1883505c1f7e32737f`；本报告另作文档提交。作者已按用户提供的信息配置，未推送远端。
- 实施依据：08 的明确规定优先，05 补充接口通则，数据库沿用已应用的 `001_init.sql`。
- B 的 21 个业务 HTTP 操作已实现；公共模型、冻结样例、C 模块、A 前端及负责人共享测试均未修改。
- 全量回归目前为 **177 passed、1 failed、0 skipped**。唯一失败是冻结共享测试仍要求绑定请求返回 `FEATURE_NOT_AVAILABLE`，与 B 启用绑定校验的目标相冲突。用户已明确要求保留原测试，交负责人更新；不能据此宣称全量测试全绿或 V1 发布通过。

## 功能与需求对应

| 需求 | B 的实现 | 验证与边界 |
|---|---|---|
| V01 | Agent 创建、分页/状态筛选、详情、部分更新、ACTIVE/DISABLED | 空白/长度/未知字段、PATCH null 语义、404/422、数据库真实读写 |
| V02 | Task 列表/详情、同 Task 多次启动 Run、Run 列表与筛选 | task_id/status/source_type/带时区时间窗口、稳定排序和分页 |
| V03 | 保留异步执行、终态查询、异常失败和启动恢复 | Agent 在创建 Run 前验证；缺失 404、禁用 409、形状错误 422；失败不创建 Run |
| V04 | 保留完整 Trace、Span/Event 分页与局部 Event 筛选 | 500 Span 完整取回，统计和页面数据使用一致读快照 |
| V05 | 跨 Trace 日志 | severity/task_id/agent_id/run_id/trace_id/error_type/from/to；通过 run_id 和 span_id 同时关联，避免跨 Run 同名 Span 串联 |
| V06 | 总览、Agent/工具/错误分组、UTC 日期趋势 | P50/P95、成功率分母、Agent LLM Token、工具总耗时、空集、日期补零、固定数据精确对账 |
| V07 | 两类隔离索引实验及历史查询 | 1 千/1 万/10 万行、真实 EXPLAIN ANALYZE、三次中位数、开关、并发冲突、超时和原子文件保存 |
| V08 | 提供原有执行/查询接口及绑定校验 | B 自有 SQL 数据验证十万 Span 查询；不冒充 C 的 HTTP 数据生成器交付 |
| V09 | 安装、原型兼容、错误格式、配置说明、测试记录 | 干净依赖环境、空库/重复迁移/已有数据保留，独立 PostgreSQL 测试库，无数据库测试跳过 |

## API 清单

所有业务路径前缀为 `/api/v1`。成功对象使用 `data/message`；列表使用 `data/meta`；错误使用 `error.code/message/details`。

| 方法 | 路径 |
|---|---|
| POST、GET | `/agents` |
| GET、PATCH | `/agents/{agent_id}` |
| POST、GET | `/tasks` |
| GET | `/tasks/{task_id}` |
| POST | `/tasks/{task_id}/runs` |
| GET | `/runs`、`/runs/{run_id}` |
| GET | `/traces/{trace_id}`、`/traces/{trace_id}/spans`、`/traces/{trace_id}/events` |
| GET | `/events` |
| GET | `/analytics/overview`、`/analytics/agents`、`/analytics/tools`、`/analytics/errors`、`/analytics/trend` |
| GET | `/benchmarks/results` |
| POST | `/benchmarks/run` |

`/health`、`/docs` 和 `/openapi.json` 保留。未新增外部 finish/采集接口、Agent 删除、Task 编辑/删除、取消 Run 或真实模型功能。REAL 仍返回 409。

## 文件与实现说明

- `backend/app/api/v1.py`：新增业务路由；`api/routes.py` 保留原型入口，传给 C 的配置使用 JSON 模式规范化 UUID。
- `backend/app/api/query.py`：校验公开查询参数名称；拒绝未知参数及 Python 内部别名。兼容锁定版本 FastAPI 对 `from`/`to` 的提取行为。
- `backend/app/schemas/v1.py`：请求/响应类型、分页、时间范围、Agent PATCH 和实验模型。直接复用负责人提供的公共 Trace 类型。极端日期转换 UTC 超出可表示范围时返回 422，避免抛出服务器错误。
- `backend/app/schemas/text.py`、`schemas/api.py`：Agent/Task 文本及日志 error_type 筛选提前拒绝 PostgreSQL 不支持的空字节，返回 422；中文、表情、多行文本正常保存。
- `backend/app/repositories/resources.py`：Agent/Task/Run 查询、分页及 Agent 启用校验。创建 Run 前持有 Agent 共享行锁，使禁用更新与启动身份校验有确定先后关系。
- `backend/app/repositories/analytics.py`：SQL 聚合和日志关联。Agent 耗时仅统计 AGENT Span，Token 单独汇总同身份 LLM Span，不重复累计父子节点。
- `backend/app/core/database.py`：查询使用 REPEATABLE READ 快照，使 total、分页数据及总览各项统计一致；写入事务隔离行为保持原型设置。
- `backend/app/repositories/execution.py`：极大页码直接返回空页；Run 结束时间使用数据库时钟并取不早于 started_at 的值，修复 Windows 上极快失败可能触发时间约束的问题。
- `backend/app/services/runs.py`：移除绑定的临时拒绝分支，执行真实数据库身份校验。
- `backend/app/services/benchmarks.py`：独立物理连接、会话级 TEMP 表、查询预算、并发保护及历史文件原子替换。历史按真实 UTC 时间排序，避免整秒与小数秒字符串的字典序错误；同一时间按 result_id 稳定排序。
- `backend/app/main.py`：注册新增路由，OpenAPI 声明统一 504 错误模型。
- `.env.example`：增加 `BENCHMARK_ENABLED=false`。
- `backend/tests/backend/`：B 自有固定数据、API、统计、事务、OpenAPI、实验测试；独立的 `scale_check.py`、`timeout_check.py`、`endurance_check.py` 必须显式运行。后者通过真实 HTTP 和独立后端进程验收并发查询与周期重启。

无新增业务表、无新迁移、无依赖升级。`001_init.sql`、现有依赖 lock 和公共契约保持原样。

## 索引实验设计与实测

服务端预定义 `TRACE_QUERY_INDEX` 与 `ERROR_PARTIAL_INDEX`；仅允许 dataset_size 为 1000、10000、100000。独立连接中的 TEMP 表依据 spans 列和检查约束构造确定性数据，不复制业务索引、不删除业务数据或索引。按 Run 分组，每组最多 500 Span。

- Trace 案例：比较无索引与 `(run_id, start_time)` 组合索引。
- Error 案例：比较无索引与 `status='ERROR'` 的时间部分索引。
- 每种方案执行三次 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`，耗时取 Execution Time 中位数，并保存该次完整计划。
- 索引创建时间不混入查询耗时。小规模实验不保证加速，禁止硬编码性能比例。
- 单次预算 120 秒；SQL 超时/取消后返回 504 `BENCHMARK_TIMEOUT`，回滚并关闭独立连接；并发实验返回 409。
- 结果保存在 `backend/var/benchmarks.json`，由运行后端的操作系统用户读写。文件读写锁、flush/fsync 和临时文件原子替换防止半写；损坏文件返回 500，不覆盖历史。
- 默认禁止执行实验，设进程环境变量 `BENCHMARK_ENABLED=true` 后重启后端启用。关闭时仍可查询历史。保持单后端进程运行。

本机 PostgreSQL 16.15 的一次真实 HTTP 验收结果，单位 ms；这些数值仅代表该次机器与数据分布：

| 案例 | Span 行数 | 无索引中位耗时 | 有索引中位耗时 |
|---|---:|---:|---:|
| Trace 组合索引 | 1,000 | 0.101 | 0.117 |
| Trace 组合索引 | 10,000 | 0.467 | 0.077 |
| Trace 组合索引 | 100,000 | 12.687 | 0.080 |
| Error 部分索引 | 1,000 | 0.052 | 0.009 |
| Error 部分索引 | 10,000 | 0.410 | 0.014 |
| Error 部分索引 | 100,000 | 12.725 | 0.062 |

完整计划留在本地 `backend/var/benchmarks.json`，不作为源码提交。

## 验证命令与结果

从仓库根目录执行，使用已有独立 `agent_observability_test` 数据库：

```powershell
$env:TEMP = "$PWD\backend\var\tmp"
$env:TMP = $env:TEMP
backend/.venv/Scripts/python.exe scripts/test_backend.py
backend/.venv/Scripts/python.exe scripts/test_backend.py tests/backend
backend/.venv/Scripts/python.exe scripts/test_backend.py tests/backend/scale_check.py -s
backend/.venv/Scripts/python.exe scripts/test_backend.py tests/backend/timeout_check.py -s
backend/.venv/Scripts/python.exe scripts/test_backend.py tests/backend/endurance_check.py -s
backend/.venv/Scripts/ruff.exe check backend scripts
```

测试入口会清空专用 `*_test` 库的五张业务表，绝不能指向开发数据。大规模、两分钟超时和持续运行测试不在默认单元测试发现范围内。持续运行测试默认 30 秒，可通过 `B_ENDURANCE_SECONDS` 调整至最多四小时，并用 `B_ENDURANCE_REPORT` 指定 JSON 报告路径；数据库仍由标准测试入口选择。运行持续测试时，不要让另一套测试清空同一个测试库。

已执行结果：

- 修改前原型基线：39 passed，0 skipped。
- 当前全量：177 passed，1 failed，0 skipped；失败原因见下节。
- B 自有测试：139 passed，0 failed，0 skipped（含追加阶段的 8 项 UTC 边界、1 项时间排序/分页、13 项文本输入回归）。
- 十万规模：1 passed；200 Run、100000 Span、200 Event、3 Agent，Token/成功率/分组/完整分页精确核对。
- 实际 120 秒超时：1 passed；120.047 秒返回 504，验证临时表清理、无半个结果落盘、下一次实验执行成功。
- Ruff、Git diff 格式检查通过。
- 真实 HTTP：42 次检查；500 Span 成功 Run、105 Span 失败 Run、资源查询/更新、日志、分析、六组实验、错误状态均通过。
- API 和 PostgreSQL 重启后，两条 Trace 与六条实验结果仍可查询；禁用实验后执行返回 409、历史仍可读。
- 追加修复后再次重启开发 API：六组资源/统计/历史响应与重启前完全一致；真实 HTTP 验证四种非法输入返回 422，且未写入数据，实验保持默认关闭。证据为 `backend/var/updated-api-verification.json`。
- 独立干净虚拟环境从原 lock 安装通过。新建 `agent_observability_install_test` 空库迁移、重复迁移通过；对已有开发库再迁移，3 Agent、1 Task、2 Run、605 Span、102 Event 均保持。
- 目前仅有 Starlette/AnyIO 的 BlockingPortal 弃用警告；未为消除此警告擅自升级依赖。

本机原始证据位于忽略提交的 `backend/var/http-acceptance.json`、`install-verification.json`、`full-test-results.txt`、`timeout-verification.txt`。

第一阶段持续运行验证于北京时间 20:06–22:22 完成，结果 passed：273 Run、136500 Span、218 成功 Run、55 个主动注入的失败 Run、56 次十万行索引实验；无验证错误。每 30 秒一个 500 Span Run，四路并发查询，逐轮核对 Run/Span 数、成功失败数、连接数量及临时表清理；逐轮采样的最大连接数为 5。使用专用 `agent_observability_soak_test` 库，数据与证据保存在 `backend/var/soak/`。该阶段独立后端已停止，开发服务保留。

用户于 22:15 追加工作，并于 23:17 明确要求完成后及时交付、无需用满时长。第二阶段按要求提前停止，状态为 `stopped_by_user`，不算完整时长验收通过。已完成的 114 轮检查均无异常：57000 Span、91 个成功 Run、23 个主动注入的失败 Run、24 次十万行实验、12 次后端进程重启；六路并发查询，逐轮采样的最大连接数为 6。使用独立 `agent_observability_endurance_test` 库；报告位于 `backend/var/endurance-report.json`。短时脚本自检 1 passed；额外验证进程已全部停止，开发服务仍正常。该显式测试仅供需要时复验，不属于日常必跑套件。

## 本机环境与启动

项目已从中文目录迁至 `E:\sjk\agent-observability`。旧 `E:\数据库` 因被进程占用保留空目录；临时 P: 映射已移除。

- Python 3.11.18 便携运行时、uv、PostgreSQL 16.15、下载/安装缓存与数据库数据均在 `backend/var/`。
- 项目虚拟环境：`backend/.venv/`；安装复验环境：`backend/var/clean-venv/`。
- 本机 PostgreSQL 仅监听 `127.0.0.1:55432`，没有安装 Windows 服务。开发库和测试库分开。
- `.env` 使用项目本地凭据并显式连接 IPv4 回环，避免 Windows localhost 回退等待；密码和数据库文件不提交。
- 当前后端监听 `127.0.0.1:8000`。若已经运行，请勿重复启动第二实例。

数据库未运行时，从根目录启动：

```powershell
& backend/var/tools/postgresql16/pgsql/bin/pg_ctl.exe -D "$PWD\backend\var\pgdata" -l "$PWD\backend\var\postgres.log" -w start
```

后端未运行时，另开终端：

```powershell
cd backend
.venv/Scripts/python.exe -m app.migrate
.venv/Scripts/python.exe -m app
```

其他成员按 README 使用 Python 3.11 与 PostgreSQL 16 即可，不依赖本机便携目录。安装 lock、配置根目录 `.env`、运行迁移后启动。此分支不需要模型密钥或外部数据。

## 负责人待处理与真实集成边界

1. **冻结测试冲突**：`backend/tests/test_shared_contracts.py::test_prototype_does_not_silently_ignore_requested_binding` 仍 monkeypatch 数据库访问为报错，并要求绑定请求一律 409 FEATURE_NOT_AVAILABLE。V1 已要求 B 查询数据库并启用合法绑定。2026-11-10 用户明确选择“保留原文件，交负责人更新”。负责人应替换为 V1 身份验证/错误分支测试，再执行全量回归；不要简单删除测试而丢失保护。
2. **C 的真实绑定继承仍待集成**：现有原型模拟器会忽略 agent_ids。本分支验证了身份校验与 JSON 传参；完整身份传播使用 B 自有固定 SimulationResult 替身验证存储、日志和统计。它不证明 C 的真实绑定/重试实现已经完成。现有原型下绑定请求可接受，但输出 Span 仍可能 agent_id=null，最终演示须合入 C 分支。
3. **A 的页面尚未联调**：冻结 21 组样例与 B 的响应模型核对通过，真实 HTTP 已验证；没有修改或宣称验收 A 的新页面。
4. **C 的十万 HTTP 生成器不在本次范围**：B 的规模验证数据由测试 SQL 直接构造，不能替代 C 的 generate_data.py 验收。
5. 负责人合并后须执行真实三方 Agent 绑定、日志与统计对账、成功/失败/恢复场景、浏览器页面、两类实验和大规模生成器验收。
6. 实现已本地提交，尚未推送；负责人可审查上述实现提交及后续交付文档提交。凭据、环境、缓存、实验 JSON 和数据库目录均未提交。
