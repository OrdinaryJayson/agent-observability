# v2 三名成员独立开发任务与可复制Prompt

状态：任务设计，尚未执行。需求编号见 [13](13-v2-overall-design.md)，数据/协议/实验/验收分别见14–16和18。三人从同一已合入设计基线的main创建 `codex/v2-frontend`、`codex/v2-backend`、`codex/v2-engine`；不重建项目，不自行合main，不互相cherry-pick未审查代码。

## 1. 文件所有权与协作边界

| 归属 | 可以修改 | 不得自行修改 |
|---|---|---|
| A | frontend/全部；docs/deliveries/A-v2.md | backend、database、scripts、根配置、公共契约 |
| B | backend/app的api/core/models/repositories/services/schemas；新增app/contracts/v2、app/worker、app/lab；backend/tests/backend_v2；database；后端依赖/lock；Compose/.env.example；docs/deliveries/B-v2.md | C的引擎/分析/时钟、前端、已有冻结公共模型与共享fixture |
| C | 新增backend/app/execution_v2、analysis_v2；backend/tests/engine_v2；scripts/v2；reports/v2（只提交脱敏小型报告和清单）；docs/deliveries/C-v2.md | B的API/SQL/迁移/队列/锁、frontend、现有v1模拟器与测试入口 |
| 负责人 | docs公共文档、README、AGENTS、contracts/v2、tests/integration_v2、共享fixture/测试入口、CI与根.gitignore | 公共调整须同步调用方与验收，不以自己的旧假设覆盖成员代码 |

B显式获得**新增**app/contracts/v2的实现责任，只能逐字段实现15/JSON Schema，不能修改已有app/contracts/execution.py、trace.py或recorder/contracts.py。模型实现不是协议自行变更权。C通过公共包导入可用类型；独立阶段其引擎使用Protocol和JSON dict，依冻结样例测试，不等待B。合并时统一使用B的校验适配器，禁止保留第二套冲突模型。

新测试各放自有目录并使用局部conftest。负责人负责把新表清理纳入**专用v2 fixture**，原五表TRUNCATE会被新外键影响，不能让三人争改根conftest；集成时更新共享fixture与旧回归。B可在自有fixture显式按依赖序清理v2测试表。所有成员都不是独自在代码库工作，不回退或覆盖他人的修改。

`scripts/v2/test_all.py`是C目录内的显式例外，由负责人创建和维护；公共集成fixtures同样归负责人。C不得在同路径另建测试入口。

## 2. A：交互可视化、运行工作台和实验展示

负责V2-01/02/06/07/09/10/11/12/14/15的前端部分及全部UI质量；不是只换皮或增加菜单。

工作包与交付：

1. **信息架构**：默认进入总览；保留原型入口与Agent/Task管理；hash直达/刷新、可分享筛选、清晰空/错误/离线状态。启动后自动打开新Run，避免手输UUID作为主要路径。
2. **工作流编辑器**：节点、边、角色、参数编辑，图/表单双视图、校验定位、草稿revision冲突处理、版本发布/复制/对比。表单暴露15的所有受支持配置，不能仅写死三个模板截图。
3. **运行图**：建议Vue Flow负责交互、ELK或Dagre负责布局；依赖版本锁定，先做50节点/500 Span性能原型再确定。明确显示逻辑DAG与Span归属树，支持折叠角色、放大/缩小/适配、搜索节点、失败/关键路径高亮、详情抽屉。500 Span可聚合到逻辑节点，多次attempt可展开，禁止静默丢节点。
4. **实时与回放**：snapshot+SSE一致接续、seq去重/补洞、断线重连、终态关闭、离开页面清理；时间瀑布图有刻度/缩放/并行区间，回放只使用持久journal。日志/节点/时间线三向联动。
5. **分析与对比**：2–5次同版本Run对齐；缺失分支、零分母和不同模式明确显示；关键路径、自耗时、排队/调度/恢复/重试代价展示算法证据与局限，不能把估计当真实因果。
6. **数据库工作台**：六类实验参数面板、队列/阶段/取消、规模/选择率/分页深度/并发曲线、置信区间、原始样本表、计划树/JSON切换、空间/写放大、导出和MV新鲜度；不只画两个柱子。
7. **质量**：桌面1440×900和移动390×844，首屏可看到主图；表格和日志虚拟滚动/有界高度；色彩以外还有状态文字与图标、键盘可操作、错误关联输入；HTTP15秒、SSE专用策略；图表/布局不抖动。

独立验收：冻结样例mock覆盖全部路由和关键边界、6类实验渲染、500 Span、105+分页、SSE重复/跳号/断线、409/412/422、取消完成竞争提示、LEGACY静态轨迹、零值与空数据、真实构建和类型检查。mock在测试配置显式启用，不改正式默认API。现有v1浏览器流程仍通过。

可复制Prompt：

```text
你是成员A，负责v2全部前端，拥有frontend/和docs/deliveries/A-v2.md。先阅读AGENTS、README、docs全部设计和contracts/v2。按13–18实现研究生课程平台的用户完整链路；保留v1，不重建项目，不修改B/C或公共协议。

从共同main创建codex/v2-frontend。立即用公共Schema和联动样例建立frontend内显式mock，不等待B。按17的A工作包完成首页总览、DAG工作流编辑/版本、队列运行中心、真实节点连线图、快照+SSE、瀑布与回放、关键路径/重试/自耗时、同版本2–5Run对比、检索、六类数据库实验、原始计划/样本/导出、数据库设计与审计。Agent/Task沿用v1接口，不复制后端管理功能。

图必须可交互且源自真实结构，不用装饰SVG冒充运行图，不用整页无限列表替代可视化。严格处理seq水位、重复/跳号、取消和重连、草稿412冲突及请求幂等键。VIRTUAL与真实墙钟、理论关键路径与实际耗时分开展示。新增前端依赖由你锁定并给出性能选择依据。

你不是独自在代码库工作，不回退他人编辑。只在自有目录实现mock和测试。交付npm ci/npm test/npm run build、mock浏览器和v1兼容测试、桌面/移动截图及视觉检查；真实全站联调由负责人集成后完成，不能用mock宣称后端已实现。A-v2.md列需求映射、文件、SHA、命令结果、性能/可访问性证据、未完成项、配置和接口疑问。公共协议冲突提出问题，不猜字段、不擅自修改合同。
```

## 3. B：数据库工程、持久化服务与实验基础设施

负责V2-02/04/05/10/11/12/14/16的数据库与服务核心，以及全部HTTP/共享校验适配器。重点是事务与一致性，不只是路由数量。

工作包与交付：

1. **数据模型**：新增迁移、目录、约束/索引、不可变版本和追加审计触发器、最小角色权限；3NF/受控冗余说明、旧库回填与checksum不变。
2. **工作流/API**：15全部路由和错误、revision/If-Match、请求幂等、Agent身份快照；公共app/contracts/v2按Schema实现并测试，无业务导入。
3. **队列Worker**：独立入口`python -m app.worker`、优先级与老化、SKIP LOCKED、15s租约/5s心跳、epoch fencing、500ms控制检查、恢复预算与截止时间；API启动不再误杀v2 Run；两个Worker实测。
4. **日志与投影**：持久batch幂等、seq连续、检查点同事务、C Sink实现、快照/SSE可重连、取消和终态竞争、最终五表投影与汇总一次提交。B自己不实现第二个DAG引擎或reducer。
5. **查询与聚合**：游标与过滤哈希、属性包含/错误文本搜索、v_run_facts/MV并发刷新/水位、v1汇总双写/回填、精确P95与近实时差异。
6. **实验基础设施**：隔离库/权限、dataset Loader、六类SQL/事务操作白名单、异步实验状态、样本与计划持久化、跨进程互斥、取消/超时/清理、环境与原始导出；保留v1实验JSON路径和旧接口。
7. **工程性**：连接池预算、长SSE不长期占数据库连接、执行等待不持锁、统一错误、脱敏、可重复安装、Worker/API日志含run_id/epoch/阶段而无凭据。

独立测试使用真实PostgreSQL专用库，固定定义/JournalBatch和C函数替身，检查约束、事务交错、队列竞争、旧epoch、ACK丢失、取消、快照与水位。实验数据B可自行构造，不等C百万生成器。不能使用SQLite、mock SQL或跳过集成测试代替数据库证据。

可复制Prompt：

```text
你是成员B，负责v2数据库、FastAPI、持久队列Worker、journal/SSE、聚合与隔离实验基础设施。拥有17第1节B的文件范围，先阅读AGENTS、README、docs全部及contracts/v2，从共同main创建codex/v2-backend。

按14新增迁移和派生视图，保留001及v1字段/响应；实现15全部HTTP、共享v2校验模型和16实验协议。修正启动恢复仅处理旧v1 Run，加入v1完成事务的LEGACY汇总双写和旧库回填，不改变旧SimulationResult/complete_run签名。实现行锁、幂等请求/批次、seq和checkpoint原子性、SKIP LOCKED、租约epoch、恢复/取消/终态竞争、C Sink、快照与SSE、游标检索、MV水位、版本不可变和审计触发器、数据库角色权限。

直接用冻结样例和固定C替身完成独立测试，不等待C引擎或A页面。C负责validate_workflow/reducer/analyze/compare，你通过冻结签名调用并提供数据库适配，不重复实现执行算法。实验仅使用专用*_lab/*_test库，六类白名单SQL与真实样本，禁止修改业务索引、接收任意SQL、硬编码加速比或用文件锁保证多Worker安全。

你不是独自在代码库工作，不覆盖别人。只新增app/contracts/v2，不改v1公共模型和根fixture。测试放tests/backend_v2；涉及共享fixture的集成需求交负责人。交付真实PG完整测试、迁移/重启/超时/双Worker/权限证据、Ruff、安装说明、API字段核对和实验原始计划。B-v2.md列需求/文件/SHA/命令/结果/固定替身范围/遗留问题，不宣称三方真实集成已通过。
```

## 4. C：DAG执行、恢复算法、分析与实证评测

负责V2-03/05/08/09/13/15的算法与实验评测，以及B/C接口的纯模块实现；不只是造随机日志。

工作包与交付：

1. **工作流语义**：三种模板、DAG/角色/分支验证、拓扑排序、确定性并发调度、MERGE与SKIPPED传播、Span归属和依赖边分离。先做小图oracle和语义反例。
2. **执行与Recorder v2**：在execution_v2新增任务隔离的异步上下文、根/角色容器、稳定node_key/attempt、真实可中断等待、虚拟时钟、节点重试、预算/取消、类型正确的Token/事件。旧v1 simulator/Recorder保持不变。
3. **检查点**：C实现execute/reduce/seal纯接口，检查点版本、逐节点确定性随机、已提交成功跳过、WorkerLost闭合、ACK不确定批次重发、恢复预算与时间边界。通过MemorySink模拟丢ACK/失租，不在引擎里导入数据库。
4. **分析算法**：选中DAG理论关键路径、自耗时区间并集、重试/恢复/调度代价、同版本运行对齐、稳健异常及明确局限；算法版本和输入水位可追溯。
5. **数据与工具**：DEMO_V2、BENCH_100K/1M、LOAD_V2，生成器/检查器、HTTP幂等和轮询、内容摘要、实际计数。业务/隔离COPY/HTTP负载三路径分别报告。
6. **评测与报告**：16故障矩阵、HTTP并发、六类实验统计与可视化、全部样本/环境/正确性报告，12分钟演示素材。B负责实际数据库机制，C组织实验顺序和证据，不在脚本复制SQL服务。

独立验收：标准库MemorySink/假HTTP服务运行，不要求B的新API先存在；有确定性成功、未恢复失败、恢复成功、取消、并行、条件分支和Worker恢复案例；算法小图独立oracle、边界和并发隔离。真正百万PG数据及跨进程故障在集成阶段按同工具完成，交付时明确未执行项。

可复制Prompt：

```text
你是成员C，负责v2 DAG执行/增量Recorder/检查点恢复、分析算法、数据生成和评测报告。拥有17规定的execution_v2、analysis_v2、tests/engine_v2、scripts/v2、reports/v2与C-v2.md。先读AGENTS、README、docs全部及contracts/v2，从共同main创建codex/v2-engine。

实现15的validate_workflow、execute_workflow、reduce_journal、seal_interrupted、analyze_run和compare_runs，严格区分归属树与依赖DAG、逻辑节点与多次attempt、真实/虚拟时间、Span状态与节点SKIPPED/CANCELLED。完成三场景、并行MERGE/条件分支、可中断等待、确定性seed、根和角色身份、预算、重试、checkpoint恢复、失租停止和丢ACK重发；不修改v1模拟器及公共协议。

立即用冻结JSON与MemorySink/故障Sink开发测试，不等待B。引擎不连接数据库、不导入B服务；B提供持久Sink。按16实现业务演示种子、百万隔离数据、HTTP负载/故障、正确性对账和实验统计报告，保留v1工具。COPY只经B的Loader适配器，实验SQL由B维护，不在脚本私造第二套数据库契约。

算法需给复杂度、独立oracle、边界/反例和局限。不能把理论关键路径当实际墙钟、子Span耗时直接相减、模拟Token当真实消耗、虚拟时间当测量性能、n<20的阈值当统计异常。真实数据和报告不能编造，未运行矩阵列出来。

你不是独自在代码库工作，不覆盖B/A。新增依赖交B管理，测试放自有目录，系统跨模块集成测试归负责人。C-v2.md交付需求映射、文件/SHA、完整命令、seed/配置、独立测试与真实实验区别、报告证据、未完成项及负责人集成步骤。
```

## 5. 工作量与交付纪律

三人的复杂度分别来自交互/渲染/实时状态、数据库/事务/持久化、调度/恢复/算法/评测，不能按文件行数判断均衡。B负担最重，优先冻结公共模型和最小Sink，不把可并行的C算法与A交互再挪给B；负责人承担集成、共享fixture、CI和协议决策。

每成员先交独立可运行骨架，再交完整功能；至少每日记录已验证事实、阻塞及接口偏差。公共变更以负责人批准的文档+Schema+样例+测试同批提交，不在聊天里口头改字段。模块交付不等于v2发布；真实验收见18。
