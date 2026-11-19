# 成员 C v2 交付记录

交付日期为 2026-11-19，时区 Asia/Shanghai。当前完成成员 C 的独立模块交付，真实三方集成与数据库实验按 18 号文档由负责人继续验收。

## 基线与提交

- 共同基线为 `19560b3505aa35769f968a66d3fd89d150eef1a0`。
- 实现分支为 `codex/v2-engine`。
- 引擎、分析、工具及测试提交为 `c1adcd4646b0ee8ac6c36a26aed52faaeee6a93b`。
- 本记录和 reports/v2 作为后续文档提交。实际执行证据记录实现 SHA 及规范化源文件 SHA256。

## 需求与修改文件

| 工作包 | 需求 | 实现与验证 |
|---|---|---|
| 三场景和 DAG 语义 | V2-02/03 | execution_v2/validation.py、templates.py；冻结 Schema、拓扑、角色、路由、后支配汇合、交叉分支反例和预算 |
| 执行和增量记录 | V2-03/05/06/07 | execution_v2/engine.py、recorder.py、clocks.py；最多四并行步骤、条件 SKIPPED、一次归属父节点、独立依赖边、UTC、真实等待及虚拟时钟 |
| 恢复与终态投影 | V2-05/14 | execution_v2/projection.py、memory.py、protocol.py；检查点水位/hash/模式校验、WorkerLost 闭合、成功节点保留、同批重发、epoch 失效停止、取消与确定性封口 |
| 分析和对比 | V2-08/09 | analysis_v2/algorithms.py；关键路径、区间并集自耗时、调度/重试/恢复代价、2–5 同版本对比、MAD 和未知 Token 的 null 语义 |
| 标准数据与 HTTP 工具 | V2-01/10/11/13 | scripts/v2 的 seed_demo.py、generate_dataset.py、load_test.py、check_run.py 及辅助模块 |
| 故障、机制驱动与报告 | V2-12/14/15 | fault_suite.py、_mechanisms.py、_resources.py、report_experiments.py、evaluate_engine.py；屏障、原样本保留、统计、图表与演示材料 |
| 独立验证 | V2-16 | backend/tests/engine_v2 下 test_engine.py、test_algorithms.py、test_mechanisms.py、test_tools.py 及局部 conftest.py |

完整新增文件清单可通过 `git show --stat c1adcd4` 查看。公共调用入口在 `app.execution_v2` 和 `app.analysis_v2`，运行引擎和 HTTP 工具使用标准库。

## 关键语义与算法证据

工作流最多 50 节点。条件采用最近公共后支配 MERGE 验证，嵌套上限四层，普通边为 ALWAYS。调度按 node_key 稳定选择，就绪后容量等待与节点操作分别记录。退避采用独立计时阶段，另一并行分支保持自身完成时刻。失败后已运行的独立分支允许闭合。

每个实例拥有独立 Recorder，异步父上下文使用 ContextVar。根 WORKFLOW 为空身份，角色容器按绑定生成，操作继承所属角色。只有 LLM 保存 Token，显式 0 得以保留。每次尝试保留独立 Span，attempt_no 从 1 递增。

检查点复用冻结形状。恢复匹配 definition_hash、clock_mode 和 journal_seq，成功节点保留，在途尝试闭合 WorkerLost 后生成新尝试。最多两次 Worker 恢复，运行预算覆盖恢复余量。虚拟恢复延续原时间原点。提交未知结果以相同 batch/event ID 和内容重发，系统事件导致的安全水位重基由 Sink 完成。

拓扑和关键路径为 O(V+E)，后支配集合在 50 节点上使用 O(V(V+E)) 上界的集合算法，自耗时使用区间排序并集。测试包含独立路径枚举 oracle、重叠/裁剪/缺失区间、n<20 和 MAD=0、跳过分支、零分母、并发随机结果及恢复时间原点。完整方法见 reports/v2/methods.md。

## 实际命令和结果

验证环境为 Windows、Python 3.11.15、PostgreSQL 16.6。完整后端测试使用本任务专用实例的 agent_observability_test，端口 55436。

```powershell
$env:DATABASE_URL='postgresql+psycopg://agent_user@127.0.0.1:55436/agent_observability'
backend/.venv/Scripts/python.exe scripts/test_backend.py
backend/.venv/Scripts/python.exe -m pytest -q backend/tests/engine_v2
backend/.venv/Scripts/ruff.exe check backend scripts
backend/.venv/Scripts/python.exe contracts/v2/validate_design.py
backend/.venv/Scripts/python.exe -S scripts/v2/evaluate_engine.py --output reports/v2
```

| 检查 | 实际结果与范围 |
|---|---|
| 完整后端入口 | 305 passed、0 skipped，包含既有 v1 测试和 55 项 C 测试；存在一条第三方 Starlette/AnyIO 弃用提示 |
| C 独立目录 | 55 passed，纯算法、MemorySink、假 HTTP 和事务日程 oracle |
| Ruff 与差异检查 | 通过 |
| 冻结设计包校验 | 2 Schema、3 工作流、2 样例批次、25 日志、6 实验样例、39 路由，通过 |
| 实际运行批次交叉校验 | jsonschema 4.23.0 对 3 工作流产生的 38 批实际数据验证通过 |
| 标准库执行入口 | 使用 -S 成功运行八个独立执行案例和六个 MemorySink 故障案例 |
| 图表工具 | 临时目录生成 4 组 SVG/PNG，使用标记的渲染冒烟数据；输出位于忽略提交目录 |

独立案例的完整定义、seed、节点状态、分析和源摘要位于 reports/v2/engine-evidence.json。并行虚拟耗时 600ms，串行 900ms，理论关键路径 600ms。research 的 seed=1、failure_probability=0.5、max_retries=2 演示失败尝试保留后恢复成功。

## 数据生成证据

```powershell
backend/.venv/Scripts/python.exe scripts/v2/generate_dataset.py --offline --profile BENCH_100K --seed 42
backend/.venv/Scripts/python.exe scripts/v2/generate_dataset.py --offline --profile BENCH_1M --seed 42
```

| profile | 实际 Run | 实际 Span | 实际 Event | 生成摘要 |
|---|---:|---:|---:|---|
| BENCH_100K | 200 | 100000 | 100000 | 278a3b7bad4add09e1370750ad246bb705463afff4f074f8df2c969d71d91f14 |
| BENCH_1M | 2000 | 1000000 | 1000000 | 5929cd96c666f3b59d0ef0914741b4a6e39330b3d344b0ec9bf64315c4b25e82 |

逐 bundle 检查单根、唯一 Span、父引用/无环、Event 引用、时间和 Token 约束、属性字节数。清单在 reports/v2/dataset-validation.json，均标注 OFFLINE_LOGICAL_STREAM、persisted=false。上述规模是已生成并检查的离线逻辑数据。真实 COPY 和 SQL 计数由集成阶段执行。

## 工具和适配器接入

```powershell
backend/.venv/Scripts/python.exe scripts/v2/seed_demo.py --base-url URL --seed 42 --profile full
backend/.venv/Scripts/python.exe scripts/v2/generate_dataset.py --base-url URL --profile BENCH_1M --seed 42
backend/.venv/Scripts/python.exe scripts/v2/load_test.py --base-url URL --clients 1,4,8,16 --runs-per-level 300
$env:ALLOW_FAULT_TESTS='true'
backend/.venv/Scripts/python.exe scripts/v2/fault_suite.py --base-url URL --scenario all --driver operator_fault_driver
backend/.venv/Scripts/python.exe scripts/v2/report_experiments.py --input exports/ --output reports/v2/
backend/.venv/Scripts/python.exe scripts/v2/check_run.py --base-url URL --run-id UUID
```

DEMO 工具创建八个语义 Agent、三类版本、六个 Task、六十个 Run，前 30 个固定同一版本，并请求两个取消。LOAD 使用固定 20 节点工作流和有界客户端，保留接受/排队/执行/SSE 样本与基础设施错误。GET 和带幂等键的 POST 有限重试，状态文件在发送前保存请求身份；未知结果重用原键。草稿发布附带 If-Match。创建 Agent/Task/Workflow/Dataset 等未约定幂等的 POST 遇到未知结果时保留 pending_posts，恢复前通过服务资源清单核对对应资源。

B 的持久 Sink 负责 seq、事务、fencing 和系统日志。终态处理将计划的 run.finished 加入待提交事件后调用 reducer，再在同事务持久化闭合结果。运行中 Snapshot 的未观察 PENDING 节点由 B 按版本定义补齐。compare_runs 的输入 dict 含 run_id、version_id、definition、projection，B 的共享适配器在边界转入此形状。

B 的 `app.lab.loader.load_dataset(dataset_id, records, expected_manifest)` 接收 methods.md 定义的逐 Run bundle。expected_manifest 提供版本、seed、配置、实际计数和内容摘要，Loader 独占 SQL/COPY、事务、schema 和权限。工具在加载前计算预期摘要，消费后再次核对，finalize 由服务端重新验证。

故障运维模块提供 `run_scenario(name, client, processes)`，必须返回 scope=REAL_SERVICE、fault_point、checks、passed。ManagedProcesses 仅停止自己启动的句柄。资源采样通过 `--resource-driver` 模块的有界 sample_resources() 接入；无采样器时资源指标为 null 并注明来源缺失。SQL 操作和数据库连接峰值采样由 B 的只读适配器提供。

统计与绘图使用 type-7、配对 bootstrap、完整样本及 Matplotlib。本地验证安装了 Matplotlib 3.10.7 和 jsonschema 4.23.0，后续集中依赖锁定交 B 管理。

## 报告和待执行验收

reports/v2 提供 experiment-report.md、methods.md、results.csv、environment.json、correctness.json、exports.json、engine-evidence.json、dataset-validation.json 和 demo-script.md。results.csv 当前为真实实验结果列定义，exports.json 为空样本清单。报告列明六类实验、全部负载档和敏感性组合的执行状态。

本基线尚无 B 的 v2 持久 Sink、Worker、Loader 和实验 API。真实百万 PostgreSQL 落库、六类数据库实验、1/4/8/16 档真实 HTTP 负载及 RSS/连接峰值、双 Worker 与完整跨进程故障矩阵均未执行。C 的假 HTTP 协议测试和 MemorySink 结果用于独立开发验收。

负责人接入 B 的共享类型与上述适配器后，按 18 执行真实全链路、数据库屏障、SQL 对账和前端联调，再使用完整原样本重建曲线与结论。12 分钟演示路线在 demo-script.md。当前交付记录不作为 v2 发布验收通过的声明。
