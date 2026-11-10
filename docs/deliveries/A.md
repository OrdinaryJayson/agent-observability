# 成员 A 前端交付记录

- 分支为 `feature/v1-frontend`，基线为 `1d7c60651ce80cc93c7aab5e1096e02db9403e0c`。
- 前端实现提交为 `cc8698258c6fa09e5b6c1fe32e883e990988276b`。
- 页面及接口按 [08 v1 范围](../08-v1-release-contract.md)、[05 HTTP 契约](../05-integration-contract.md) 和 [09 成员 A 任务](../09-v1-member-prompts.md) 验收。

| 需求 | 交付内容 | 主要文件 |
| --- | --- | --- |
| V01 | Agent 列表、状态筛选、详情、新建、部分字段编辑、启停 | `frontend/src/pages/AgentsPage.vue` |
| V02 | 创建及查看 Task、同一 Task 多次模拟执行、按顺序绑定 1–3 个 ACTIVE Agent、Run 历史筛选和分页 | `frontend/src/pages/TasksPage.vue`、`RunsPage.vue` |
| V03–V04 | 保留首页快速执行和 Run ID 恢复。支持历史轨迹直达及刷新、2 秒轮询、完整 Span 和 Event 分页、调用树、相对时间线与节点事件联动。Span 分页数量与 Trace 概览不一致时提示重试 | `frontend/src/pages/TracePage.vue`、`frontend/src/utils/tree.ts`、`routes.ts` |
| V05 | 全局事件的等级、任务、Agent、Run、Trace、错误类型和时间筛选，点击关联到 Span 与 Event | `frontend/src/pages/LogsPage.vue` |
| V06 | 总览、平均/P50/P95、Token、按 UTC 日补零的趋势、异常分布、Agent 与工具统计 | `frontend/src/pages/OverviewPage.vue`、`PerformancePage.vue`、`frontend/src/utils/trend.ts` |
| V07 | 两种索引实验与三种规模、前后耗时与计划、历史分页和加速比、失败及超时提示 | `frontend/src/pages/BenchmarksPage.vue` |
| V08（前端部分） | 保留原型不绑定执行，正式运行可填写 seed、失败率和 Span 数量。恢复重试的结果按契约显示 Run 状态及错误 Span | `frontend/src/pages/TasksPage.vue`、`TracePage.vue` |
| V09（前端部分） | 可直达和刷新的 hash 导航、共享加载与错误状态、分页、UTC 筛选与本地时区显示。普通请求 15 秒，实验执行 150 秒 | `frontend/src/App.vue`、`style.css`、`api/client.ts`、`types/index.ts`、`components/`、`composables/requests.ts`、`utils/format.ts` |

## 独立验收

Windows，Node.js 22.20.0，Edge 无头浏览器。从 `frontend/` 执行。

| 命令 | 结果 |
| --- | --- |
| `npm ci --offline --no-audit --no-fund` | 在独立临时目录从同一份 lock 安装，成功安装 92 个依赖包 |
| `npm test` | 6 项通过，包含原型树与分页回归、普通和实验请求超时检查 |
| `npm run build` | Vue TypeScript 检查和 Vite 生产构建通过 |
| `$env:PLAYWRIGHT_CHANNEL = 'msedge'` 后执行 `npm run test:e2e:mock` | 8 项通过。覆盖全部业务页面、分页不完整后重试并取回 105 个 Span 和 101 条事件、成功 Run 包含错误 Span、两种索引实验、UTC 查询边界、零 Span 失败、刷新与移动端 |
| `npm run test:e2e` | 原型真实后端套件保留。此次机器未运行原型 API 和 PostgreSQL，未执行该套件 |

Mock 套件位于 `frontend/tests/v1.mock.e2e.ts`，直接读冻结的 HTTP 合成样例，在独立的 `127.0.0.1:5174` 上拦截请求。模拟数据和索引耗时仅用于验证界面。默认开发及生产构建从 `VITE_API_BASE_URL` 读取真实服务地址。

## 联调配置

1. 按仓库 README 启动数据库及已集成的 v1 后端，在 `frontend/.env.local` 中将 `VITE_API_BASE_URL` 指向其 `/api/v1` 地址，然后执行 `npm run dev`。A 无额外迁移。
2. 负责人合并后验证真实 Agent 绑定、恢复重试、日志及统计对账、实验服务及重启后的历史。运行实验前在后端显式设置 `BENCHMARK_ENABLED=true`。数据生成工具和实际执行计划由对应后端交付提供。
