# 成员 A v2 前端交付记录

- 共同基线 `19560b3505aa35769f968a66d3fd89d150eef1a0`，实现分支 `codex/v2-frontend`。
- 实现提交 `5f2a2b67d6c208df4ec18b8b3e80f470090a958c`。接口依据为 [15 公共契约](../15-v2-contracts.md) 和 [公共设计样例](../../contracts/v2/README.md)。
- 状态为前端独立实现及 mock 验证通过。真实 v2 三方联调和正式性能验收由负责人集成后执行。

| 需求 | 实现与文件 | 已验证 |
| --- | --- | --- |
| V2-01、V2-11 | `src/App.vue`、`OverviewV2Page.vue`。总览为默认入口，按模式显示指标、队列、近期运行、趋势和数据量，展示聚合水位，支持从近期记录打开示例轨迹。 | 首屏、各主导航、移动端、时区与 v1 回归 |
| V2-02 | `WorkflowsPage.vue`、`GraphView.vue`、`graph.ts`。草稿创建与编辑、图和表、角色/节点参数/依赖边、服务端校验定位、修订号冲突、发布、版本复制及定义差异。 | 412 后保留本地编辑、422、有效/无效校验、带定义哈希与 If-Match 发布 |
| V2-03–05 | `RunsV2Page.vue`、`state.ts`。沿用 v1 Task 和 Agent 接口，选择已发布版本、绑定角色、排队、查看状态、取消和重新提交。 | 丢响应后刷新仍使用原请求键与请求体、409、取消与完成竞争反馈 |
| V2-06–08 | `TraceV2Page.vue`、`GraphView.vue`、`journal.ts`、`Waterfall.vue`。依赖图与 Span 归属树、缩放/定位/折叠、节点/尝试/事件详情、相对瀑布、已提交日志回放、关键路径与耗时证据。 | 50 节点、500 Span、跳号补洞、重复事件、断线重连、410 后重取快照、LEGACY 静态轨迹 |
| V2-09–10 | `ComparePage.vue`、`SearchPage.vue`。同版本同模式比较、指标和节点对齐、日志和 Span 检索、游标与可分享过滤链接。 | 同版本对比、检索游标保留条件、刷新、跨页直达 Span |
| V2-12–15 | `ExperimentsPage.vue`、`ExperimentSweep.vue`、`PlanTree.vue`、`DataPage.vue`。六类参数、阶段及取消、原始样本、计划树和 JSON、实际规模/参数曲线、CI、下载、数据集登记、表关系、目录、SQL 模板、聚合刷新与审计。 | 六类提交参数和样本展示、历史实验选择率对比、CSV 下载、目录/审计 |
| V2-16 | `frontend/tests/`、`frontend/playwright.v2.mock.config.mjs`、`journal.test.ts`。保留 v1 接口和页面，快速执行入口迁到 `#/quick`，其余已有 v1 直达链接保留。 | v1 mock 套件、Node 22 构建、桌面/移动布局 |

以上页面、组件和 API 类型位于 `frontend/src/v2/`，路由入口见 `frontend/src/App.vue`。图采用 Vue 节点和视口范围内的 Canvas 连线。节点可由键盘聚焦、点击及切换为列表。表格、日志和瀑布图采用有界滚动。沿用 Vue 与锁文件，图和请求层使用浏览器 API。

## 实际验证

2026-11-17，Windows，Node.js 22.20.0，Edge 无头模式。命令从 `frontend` 目录运行。

| 命令 | 结果 |
| --- | --- |
| `npm ci --offline --no-audit --no-fund` | 在独立临时目录按同一锁文件安装 92 个包 |
| `npm test` | 8 项通过，含 v1 单元回归和 v2 字节分片、终态投影及序号检查 |
| `npm run build` | Vue TypeScript 检查及 Vite 构建通过 |
| `npm run test:e2e:mock` | v1 8 项通过，含 105 Span 和 101 事件 |
| `npm run test:e2e:v2:mock` | v2 7 项通过，覆盖主路线、跨页、SSE 边界、500 Span、全部六类实验 |
| `npm run test:e2e`、`npm run test:e2e:real` | 本轮未运行真实 v1 浏览器套件。当前机器没有运行专用 PostgreSQL 和 v1 API。 |
| 真实 v2、性能和规模验收 | 待集成。当前共同基线没有 v2 后端与 Worker，模拟浏览器结果不能用于正式耗时、资源或数据库实验结论。 |

使用 Edge 时先执行 `$env:PLAYWRIGHT_CHANNEL='msedge'`。两个 mock 套件分别在 5174 和 5175 端口拦截请求，正式构建默认请求真实接口。截图使用冻结样例，桌面 1440×900 与移动 390×844。

- 桌面轨迹截图 `C:/Users/86159/.codex/visualizations/2026/11/09/01a1c019-f88a-7c01-a0be-da6d4959c9f0/agent-v2-trace-desktop.png`
- 手机总览截图 `C:/Users/86159/.codex/visualizations/2026/11/09/01a1c019-f88a-7c01-a0be-da6d4959c9f0/agent-v2-overview-mobile.png`

## 集成配置与待核对项

1. 以 Node 22 执行 `npm ci`、`npm run dev`。从 `VITE_API_BASE_URL` 推导 v2 地址，分别部署时设置 `VITE_V2_API_BASE_URL` 为实际 `/api/v2`。在 v2 入口返回 HTTP 404 时，首页展示可用的 v1 总览。
2. 前端依据 [15](../15-v2-contracts.md) 处理普通请求 15 秒超时、SSE 心跳及重连、水位校验、修订号和幂等请求头。负责人集成后用真实 API 核对 CORS、断线/终态、游标响应、取消竞争和旧数据的 LEGACY 入口。
3. 总览示例从当前统计响应的近期运行中查找。缺少相应运行时显示空状态，课程演示需要 C 的数据种子。趋势行的指标键和实际环境字段需在真实 OpenAPI 和返回数据上对照。
4. 执行 [18](../18-v2-acceptance.md) 的图交互性能采样、键盘与两种视口验收、真实浏览器流程、数据库实验原始数据核对和聚合精确对账。本次 500 Span 已验证所有节点可达，尚未测真实服务的首屏 P95 和选择延迟 P95。
