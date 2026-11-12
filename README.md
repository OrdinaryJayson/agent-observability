# AI Agent 执行轨迹管理与可观测性分析系统

基于 PostgreSQL 的 AI Agent 执行轨迹管理与可观测性分析系统。当前为 **v1 课程项目**，支持 Agent 与任务管理、模拟执行、Trace/Span 可视化、日志检索、性能统计及数据库索引实验。

## 当前功能

- Agent 创建、编辑、启停和查询；Task 创建、详情及多次运行；Run 分页和筛选。
- 模拟研究场景：Agent 绑定、固定 seed、失败与一次恢复重试；无模型密钥也可使用。
- Trace 树、时间线、Span 与事件详情；跨 Trace 日志筛选与跳转。
- 运行总览、P50/P95、Token、趋势、Agent/工具/异常分析。
- 两项隔离索引实验，展示真实前后执行计划、耗时和历史记录。
- PostgreSQL 迁移、单事务持久化、失败恢复、自动化测试及数据生成工具。

本版运行于本地单后端实例。真实模型 Adapter、外部采集、任务取消、持久化队列和权限管理为后续扩展，当前不提供。

## 技术栈与环境

Python 3.11、FastAPI 0.115、SQLAlchemy 2、Pydantic 2、PostgreSQL 16、Node.js 22、Vue 3、TypeScript 5。需要 Docker Compose V2，也可使用等价的本地 PostgreSQL 16。依赖版本记录在后端 lock 文件和前端 package-lock.json。

## 启动

以下 PowerShell 命令从仓库根目录执行。先安装 Python 3.11、Node.js 22，并启动 Docker Desktop。Linux/macOS 将 Windows 的 .venv/Scripts/python.exe 路径换成 .venv/bin/python。

1. 复制模板，编辑根目录 `.env`，为 `POSTGRES_PASSWORD` 设置本地密码。`DATABASE_URL` 留空时，后端根据 POSTGRES_* 自动生成连接地址，支持特殊字符密码。端口被占用可修改 POSTGRES_PORT，默认 5432。已有配置不要再次覆盖。

```powershell
Copy-Item .env.example .env
docker compose up -d db
docker compose ps
```

2. 数据库健康后安装后端依赖、迁移并启动。保持该终端运行。没有 py 命令时使用对应的 Python 3.11 可执行文件创建 venv。

```powershell
cd backend
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.lock
.venv/Scripts/python.exe -m app.migrate
.venv/Scripts/python.exe -m app
```

3. 新开终端，从仓库根目录启动前端：

```powershell
cd frontend
Copy-Item .env.example .env.local
npm ci
npm run dev
```

打开 [页面](http://127.0.0.1:5173)、[API 文档](http://127.0.0.1:8000/docs) 或 [健康检查](http://127.0.0.1:8000/health)。可在 Agent 管理中创建并启用 Agent，在任务管理中创建 Task、绑定 Agent 并执行，在运行历史或日志中查看 Trace；总览、性能和数据库实验从导航进入。

数据库实验默认关闭；本地演示需在根目录 `.env` 设置 `BENCHMARK_ENABLED=true` 并重启后端。实验使用临时表及索引，结果保存在本地 `backend/var/benchmarks.json`，实际耗时取三次测量中位数。不要把它当作生产数据库性能结论。大规模数据可运行 `backend/.venv/Scripts/python.exe scripts/generate_data.py --help`，先确认 API 连接的是专用测试库。

后端从仓库根目录读取 .env，进程变量优先；`python -m app` 使用 API_HOST/API_PORT。前端从 frontend/.env.local 读取 VITE_API_BASE_URL。改变前端端口需同步 CORS_ORIGINS。真实密钥、.env、.env.local 均不提交。

## 测试

从仓库根目录创建独立测试库（仅首次），然后执行：

```powershell
docker compose exec -T db createdb -U agent_user agent_observability_test
backend/.venv/Scripts/python.exe scripts/test_backend.py
backend/.venv/Scripts/ruff.exe check backend scripts
cd frontend
npm test
npm run build
```

测试脚本使用开发库名加 `_test` 的独立数据库，也可通过 TEST_DATABASE_URL 指定；会清空其中五张业务表。修改用户名或库名后须同步调整 createdb 命令。直接运行 pytest 且未设测试库时，数据库测试会明确跳过；完整验收应使用测试脚本。

后端启动后，可在 frontend/ 下运行浏览器测试；Playwright 启动或复用前端：

```powershell
npx playwright install chromium
npm run test:e2e
npm run test:e2e:mock
```

Windows 已安装 Edge 时可跳过下载，设置 `$env:PLAYWRIGHT_CHANNEL='msedge'` 后执行 npm run test:e2e。原型浏览器测试会向其后端数据库写入少量测试任务；后端测试使用独立测试库。完整真实服务联调需使用专用数据库，启动 8101 测试后端并启用实验后执行 `npm run test:e2e:real`，详见[集成验证记录](docs/12-v1-integration-verification.md)。截图位于忽略提交的 frontend/test-results/。

## 目录

```text
frontend/src/             v1 页面、API 客户端、类型、Trace 树工具
frontend/tests/           浏览器测试
backend/app/api/          原型及 v1 业务接口
backend/app/core/         配置、连接、错误类型
backend/app/schemas/      HTTP 数据模型
backend/app/models/       迁移表结构反射
backend/app/repositories/ 数据访问
backend/app/services/     调度、校验、完成事务
backend/app/recorder/     内存采集与 B/C 交接类型
backend/app/simulator/    模拟研究场景
backend/app/adapters/     真实模型扩展位置，当前未实现
backend/tests/            单元、数据库与 API 测试
database/migrations/     SQL 迁移
database/benchmarks/     数据库实验相关资料
scripts/                 测试入口
docs/                    设计、契约、交接与验证记录
```

## 设计文档与协作

分工已调整为 [独立开发安排](docs/11-independent-development.md)：公共类型已提供，A/B/C 无需等待其他成员先交代码，跨模块真实验收由负责人统一完成。

正式 v1 的范围和验收以 [范围与集成契约](docs/08-v1-release-contract.md) 为准；[集成验证记录](docs/12-v1-integration-verification.md) 说明已完成检查及限制。[三名成员开发 Prompt](docs/09-v1-member-prompts.md) 和 [审查记录](docs/10-v1-readiness-audit.md) 保留为协作历史。

- [总体设计](docs/01-overall-design.md)
- [数据库与 API](docs/02-database-api-spec.md)
- [工程规范](docs/03-development-guide.md)
- [团队分工](docs/04-team-tasks.md)
- [开发与联调契约：公共边界的实施依据](docs/05-integration-contract.md)
- [原型交接：功能、扩展入口、待办和注意事项](docs/06-prototype-handoff.md)
- [原型验证记录](docs/07-prototype-verification.md)

负责人负责架构、契约和验收；A 负责前端，B 负责后端与数据库，C 负责 Recorder、模拟器和系统测试。先读 [AGENTS.md](AGENTS.md) 和设计文档，在功能分支开发，经审查后合并。基于现有入口扩展，公共字段和契约变更须同步调用方与测试。当前仅支持单后端实例；进程中断会丢失尚未落库的 Trace，重启后遗留 Run 标为 FAILED。
