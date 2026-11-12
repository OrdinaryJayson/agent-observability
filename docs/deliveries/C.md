# 成员 C 交付记录

交付日期为 2026-11-12，时区 Asia/Shanghai。

## 基线与提交

- 基线为 `origin/main` 的 `1d7c60651ce80cc93c7aab5e1096e02db9403e0c`，包含公共契约解耦 PR #3。
- 开发分支为 `feature/v1-simulator`。
- 实现与测试提交为 `667b76e947e9e38e109e91f1bc332e8a67e3d720`。交付记录单独提交在同一分支，最终分支包含两次提交。
- 实施范围依据 08、09、11 的成员 C 独立开发安排。

## 功能与文件

| 需求 | 已交付内容 | 文件 |
|---|---|---|
| V03、V08 | research 三角色执行、成功与未恢复失败、按列表顺序绑定 Agent、LLM/TOOL 继承角色身份、根 WORKFLOW 身份为空 | `backend/app/simulator/runner.py` |
| V04、V06 | 完整父子树、操作/角色/交接/重试事件、UTC 时间、LLM 独占 Token、绑定身份可供后续查询和聚合 | `backend/app/simulator/runner.py`、`backend/app/recorder/recorder.py` |
| V08 | seed 复现结构、事件和随机结果，失败操作最多重试一次，新 Span 携带 `retry_count=1`，重试计入总预算 | `backend/app/simulator/runner.py` |
| V04、V08 | Recorder 实例独立栈、单根、500 Span/2000 Event 上限、异常收尾、结果深拷贝 | `backend/app/recorder/recorder.py` |
| V08 | 标准库 HTTP 生成器、参数校验、单 Task 多 Run、终态轮询、实际持久化数量摘要、有限 GET 重试、POST 单次发送 | `scripts/generate_data.py` |
| V09 | 绑定/继承、无绑定兼容、固定 seed、恢复/失败、数量边界、并发、HTTP 序列化/异常/超时/退出码测试 | `backend/tests/simulator/test_execution.py`、`backend/tests/simulator/test_generator.py` |
| V09 | 本交付记录 | `docs/deliveries/C.md` |

每个 Run 先确定总 Span 预算，再分配到可容纳的前若干角色。角色内部的首次操作为 LLM，后续为搜索工具，重试使用该角色剩余预算。失败率为 0 时全部成功，为 1 时失败操作直接保留错误，为中间值时允许一次恢复。恢复成功的角色和根保持 SUCCESS，原失败子 Span 保持 ERROR。

## 生成器使用和行为

从仓库根目录执行，后端按 README 安装、迁移并启动。

```powershell
backend/.venv/Scripts/python.exe scripts/generate_data.py
backend/.venv/Scripts/python.exe scripts/generate_data.py --base-url http://127.0.0.1:8000/api/v1 --runs 200 --spans-per-run 500 --seed 42
backend/.venv/Scripts/python.exe scripts/generate_data.py --runs 2 --spans-per-run 8 --agent-ids '11111111-1111-4111-8111-111111111111,22222222-2222-4222-8222-222222222222'
```

最后一条命令中的 UUID 是参数格式示例，集成服务验收时应替换为已有 ACTIVE Agent 的 ID。

- 五个参数和默认值与 08 第 7 节一致。`runs` 必须为正整数，Span 数为 1–500，绑定列表为 1–3 个去重 UUID。
- 创建一个 Task，串行运行。每个 Run 的 `min_spans=max_spans=spans-per-run`，失败率沿用 0.1，第 i 个 Run 使用 `seed+i`，i 从 0 开始。有绑定时 `agent_count` 为列表长度，无绑定时为 3。
- 仅调用已有的 Task 创建、Run 启动、Run 查询和 Trace 概览接口。数据生成通过业务服务正常落库。
- HTTP 单请求上限为 15 秒，单 Run 终态轮询及概览读取预算为 120 秒，轮询间隔为 0.2 秒。GET 对网络异常、截断响应、429 和 5xx 最多尝试三次，POST 发送一次。重定向被拒绝。
- stdout 输出 JSON 摘要，包含参数、Task ID、已接受/已完成/成功/失败 Run 数、最后 Run ID、实际 Span 数和完成标志。stderr 输出失败原因。正常退出为 0，执行失败或中断为 1，非法命令行参数为 2。
- 失败业务 Run 的完整 Trace 计入实际数量。零 Span、数量不符、非法概览、未知状态和超时均结束生成并返回非零，保留已确认数量和恢复查询所需 ID。

## 自动化验证

环境为 Windows、Python 3.11.15、PostgreSQL 16.6，Python 依赖使用仓库的 `backend/requirements-dev.lock` 安装。原型服务监听 `127.0.0.1:58000`，独立验收 PostgreSQL 监听 `127.0.0.1:55432`。测试库为 `agent_observability_test`，生成库为 `agent_observability`，均来自本次工作区新建的专用 PostgreSQL 实例。

```powershell
$env:DATABASE_URL='postgresql+psycopg://agent_user@127.0.0.1:55432/agent_observability'
backend/.venv/Scripts/python.exe scripts/test_backend.py
backend/.venv/Scripts/python.exe -m pytest -q backend/tests/simulator
backend/.venv/Scripts/ruff.exe check backend scripts
backend/.venv/Scripts/ruff.exe format --check backend/app/recorder/recorder.py backend/app/simulator/runner.py backend/tests/simulator scripts/generate_data.py
git diff --check
python scripts/generate_data.py --help
```

| 检查 | 实际结果 |
|---|---|
| 完整后端入口 | 111 passed，全部数据库测试执行，0 skipped |
| 成员 C 独立套件重复运行 | 72 passed |
| Ruff | All checks passed |
| 修改的 Python 文件格式 | 5 files already formatted |
| Git 差异 | 通过 |
| 系统 Python 独立运行生成器帮助 | 退出码 0，标准库入口正常 |

完整后端回归覆盖了已有真实 API 成功/失败、105 Span 分页、事件筛选、后台异常、重启恢复、事务回滚、完成竞争、公共契约和 CORS。第三方 Starlette TestClient 有一条 anyio 弃用提示。

生成器协议测试使用本机临时 HTTP 假服务，覆盖绑定序列化、GET 重试及耗尽、POST 失败单次发送、断连、截断响应、非法 JSON、重定向、未知状态、轮询超时及实际数量不足。纯模块绑定测试使用合法 UUID，按公共契约独立检查身份继承。以下十万数据及恢复演示使用真实后端和 PostgreSQL。

## 十万数据真实验收

实际执行命令如下，退出码为 0。

```powershell
backend/.venv/Scripts/python.exe scripts/generate_data.py --base-url http://127.0.0.1:58000/api/v1 --runs 200 --spans-per-run 500 --seed 42
```

生成器逐 Run 查询真实 Trace 概览，输出如下。

```json
{
  "parameters": {
    "base_url": "http://127.0.0.1:58000/api/v1",
    "runs": 200,
    "spans_per_run": 500,
    "seed": 42,
    "agent_ids": null
  },
  "task_id": "a25546ca-5666-4f63-96ac-6e5b47c34500",
  "accepted_runs": 200,
  "completed_runs": 200,
  "success_runs": 3,
  "failed_runs": 197,
  "actual_spans": 100000,
  "last_run_id": "1b219439-df21-4355-a2fd-ab856cf69c65",
  "complete": true
}
```

只读 SQL 再次核对该 Task 的实际数据，结果如下。

| 项目 | 结果 |
|---|---:|
| 不同 Run 数 | 200 |
| Span 总数 | 100000 |
| 单 Run 最少/最多 Span | 500 / 500 |
| Event 总数 | 209347 |
| 单 Run 最少/最多 Event | 1032 / 1065 |
| 找不到同 Run 父 Span 的子节点 | 0 |
| 非 LLM 携带 Token 的 Span | 0 |

使用的核对查询如下。

```sql
SELECT r.task_id, count(DISTINCT r.run_id) AS runs, count(s.span_id) AS spans
FROM runs r JOIN spans s USING (run_id)
GROUP BY r.task_id;

SELECT min(n), max(n)
FROM (SELECT count(*) n FROM spans GROUP BY run_id) q;

SELECT min(n), max(n), sum(n)
FROM (SELECT count(*) n FROM span_events GROUP BY run_id) q;

SELECT count(*) AS missing_parent
FROM spans s LEFT JOIN spans p
  ON p.run_id=s.run_id AND p.span_id=s.parent_span_id
WHERE s.parent_span_id IS NOT NULL AND p.span_id IS NULL;

SELECT count(*) AS non_llm_tokens FROM spans
WHERE operation_type <> 'LLM'
  AND (input_tokens IS NOT NULL OR output_tokens IS NOT NULL);
```

以上 SQL 在追加下面的恢复演示 Task 之前执行。生成器运行产生的错误来自配置的模拟业务失败，各失败 Run 都保存了完整 500 Span。

## 固定 seed 恢复演示

使用已有 Task 启动接口，配置如下。

```json
{
  "simulation_config": {
    "min_spans": 8,
    "max_spans": 8,
    "agent_count": 1,
    "failure_rate": 0.1,
    "seed": 6
  }
}
```

真实 HTTP 验证 Run `52a5118b-b18e-4c3f-b331-c0c7863ff2a0`、Trace `37da400285eebd7385ab22737f85f562`，最终 SUCCESS，8 Span，1 ERROR Span。自动化测试同步断言新重试 Span 的 `retry_count=1` 和固定 seed 复现。

## 集成步骤与后续验收

本交付沿用公共模型和现有迁移，安装与迁移按 README 执行即可。负责人合入成员 B 后，使用真实 ACTIVE Agent 重新运行带 `--agent-ids` 的生成命令，验收数据库身份校验、日志与统计对账，并与成员 A 页面完成真实联调。当前共同基底的 HTTP 显式绑定仍返回约定的临时 409，B 负责替换该分支。

真实模型 Adapter 属于 08 约定的选做扩展，本次交付完成 C 的 v1 必做范围。完整 v1 发布验收由负责人按 08 第 8 节执行。
