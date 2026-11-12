# v1 集成验证记录

验证日期：2026-11-12（Asia/Shanghai）。集成基线：origin/main 1d7c606，前端 PR #4 9929879、后端 PR #5 ca20605、模拟器 PR #6 80515c3；三个分支组合到 integration/v1，未改写各成员分支。

## 已解决的集成问题

1. 公共测试从原型的“绑定一律拒绝”更新为真实 Agent 身份与落库验收：有效 Agent 的 AGENT/LLM Span 保留 ID，工作流根为 null，统计包含该 Agent；不存在与禁用状态分别返回 404/409。
2. 趋势接口改为仅返回有运行记录的 UTC 日期，空日期由前端补零；更新空集及跨空日期分页测试，避免后端为宽时间范围生成大量零值行。
3. 新增 Playwright 真实服务集成测试，以专用数据库验证页面与真实 API/模拟器/数据的端到端链路；原有 mock 测试保留并与真实测试区分。

## 验证环境与结果

Windows，Python 3.11、Node.js 22、PostgreSQL 16（Docker），Edge。后端测试和浏览器/规模验证分别使用独立的 *_test 数据库，未清空开发库；后端数据库地址仅保存在本地环境变量。

| 项目 | 结果 |
|---|---|
| PostgreSQL 后端全量 `pytest -q` | 250 passed，0 skipped；另有 Starlette/AnyIO 弃用警告 |
| 前端 `npm ci`、`npm test`、`npm run build` | 依赖安装和生产构建成功，6 项单元测试通过 |
| mock 浏览器 `npm run test:e2e:mock` | 8 项通过；仅验证模拟 API，不作为真实联调证据 |
| 真实浏览器 `npm run test:e2e:real` | 1 项通过：真实 API、PostgreSQL、Agent 绑定、105 Span、日志跳转、总览、性能及两个 1000 行索引实验 |
| 原型兼容浏览器 `npm run test:e2e` | 3 项通过，使用真实集成后端 |
| 10 万 Span 生成器 | 对专用库实际生成 200 Run，100000 Span；3 成功、197 模拟失败；退出成功 |
| 数据库核对 | 按生成 Task 查询 200 个不同 Run、100000 Span；非 LLM Span 中非空 Token 为 0 |
| 重启持久性 | 重启测试后端并重复迁移后，200 个生成 Run 和 3 条实验历史仍可查询 |
| 静态检查 | Ruff、文档链接和 Git 差异格式检查通过 |

真实浏览器测试创建了三个 ACTIVE Agent，检查 Agent 编辑、绑定执行、真实 LLM Span Agent ID 与 Token 汇总、105 Span 分页构树、全局日志定位、总览和 Agent 性能展示；两种实验使用 1000 行规模，并查看刷新后的历史。生成器采用 seed=42、500 Span/Run、默认 failure_rate=0.1；模拟失败并不表示生成器失败，200 个 Run 均保存完整 Span。本次生成 Task ID `fc394ec4-6c06-4b6f-828b-546dbc7984c4`；该数据只存在本机独立测试库，不随代码提交。

## 复验与边界

普通安装和回归按 README。真实浏览器测试使用 `frontend/playwright.real.config.mjs`，默认要求独立 v1 后端在 127.0.0.1:8101、且显式允许前端 127.0.0.1:5173；该测试创建数据并运行索引实验，须连接专用测试数据库并显式启用 BENCHMARK_ENABLED，不能指向重要数据。可通过 V1_E2E_API_URL 修改目标。仅在这些条件满足时运行 `npm run test:e2e:real`。

真实模型、持久化队列、多实例和权限控制不属于既定 v1 范围；没有真实模型调用和生产性能结论。测试不证明在所有机器、数据规模和故障条件下没有缺陷。实验结果的本机 JSON、凭据、测试库及截图均不提交。各成员原交付说明在 docs/deliveries/ 中保留为历史记录。

### 本机复验真实浏览器链路（PowerShell）

从仓库根目录创建专用数据库（仅首次，已经存在无需重复）：

```powershell
docker compose exec -T db createdb -U agent_user agent_observability_v1e2e_test
```

在新 PowerShell 终端设置以下仅对该终端有效的变量，运行迁移并启动专用后端。根目录 .env 必须已按 README 配好 POSTGRES_USER、POSTGRES_PASSWORD、POSTGRES_PORT；本步骤故意清空该进程的 DATABASE_URL，使其使用这组 POSTGRES_* 和专用库名：

```powershell
$env:DATABASE_URL = ''
$env:POSTGRES_DB = 'agent_observability_v1e2e_test'
$env:API_PORT = '8101'
$env:BENCHMARK_ENABLED = 'true'
cd backend
.venv/Scripts/python.exe -m app.migrate
.venv/Scripts/python.exe -m app
```

在另一终端从仓库根目录运行测试；确保本机 5173 未被其他前端占用，且测试后端的 CORS_ORIGINS 包含 http://127.0.0.1:5173。默认使用 Playwright Chromium；如已安装 Edge，可先设置 `$env:PLAYWRIGHT_CHANNEL='msedge'`。

```powershell
cd frontend
npm run test:e2e:real
```

测试会在指定专用库中新增 Agent、Task 和 Run，并在本机 `backend/var/benchmarks.json` 追加两条实验记录；不会清空数据库或删除已有实验记录。原型兼容浏览器测试若也使用该专用后端，请在 frontend 终端设置 `$env:VITE_API_BASE_URL='http://127.0.0.1:8101/api/v1'` 后运行 `npm run test:e2e`。
