# 原型验证记录

验证日期：2026-11-09（Asia/Shanghai）。该记录对应 0.1.0 最小原型，不等于完整系统验收。

## 环境

Windows，Python 3.11.16，Node.js 22.20.0，PostgreSQL 16.14（postgres:16 Docker 镜像），Vue 3.5.13，FastAPI 0.115.12。具体 Python 和 npm 依赖见 lock 文件。

本机 5432 已被其他项目占用，使用本项目独立 Compose 容器和 POSTGRES_PORT=55432；配置只写在忽略提交的根目录 .env，其他队员可使用默认 5432。开发库和 *_test 库彼此独立。浏览器验证使用 Edge 无头模式。

## 已执行检查

| 检查 | 命令/方法 | 结果 |
|---|---|---|
| Compose | docker compose config --quiet、up -d db、ps | 配置有效，数据库 healthy |
| 数据库迁移 | backend 中 python -m app.migrate，重复执行 | 首次成功，第二次不重复建表；迁移记录存在 |
| 后端 | 根目录 python scripts/test_backend.py（使用后端 venv） | 29 项通过，数据库集成测试未跳过 |
| 静态检查 | ruff check backend scripts | 通过 |
| 前端单元测试 | frontend 中 npm test | 5 项通过 |
| 类型检查与生产构建 | npm run build | vue-tsc 与 Vite 构建通过 |
| 浏览器流程 | PLAYWRIGHT_CHANNEL=msedge，npm run test:e2e | 3 项通过 |
| 视觉检查 | 查看实际浏览器 desktop/mobile 截图 | 桌面双栏、手机单栏，页面无横向溢出 |

后端测试覆盖：seed/Span 数量 1–500/失败率、异常收尾、非法树/时间/Token/Event、SQL 迁移重复执行、真实数据库约束失败后的整批回滚、两个完成请求竞争、失效 Agent 外键、HTTP 成功与失败流程、105 Span 分页、事件筛选、后台异常无 Trace、重启恢复、404/409/422、OpenAPI 模型。

浏览器测试覆盖：创建并执行成功、选择 Span、刷新后恢复 Run；手机失败 Run 和错误事件；查询失败后重试且不新建 Run。浏览器测试会产生少量模拟任务，不接触模型 API。

## 尚未验证及已知限制

- 未调用真实模型，未做数据库性能实验，不报告优化比例。
- 未验证多实例、生产部署或持久化队列；当前明确仅单实例。
- 其他操作系统尚未实际运行；SQL/Python/Vue 入口保持跨平台，README 提供 venv 路径调整方法。
- 第三方测试依赖可能输出弃用/终端颜色提示，未影响上述结果。
- 浏览器截图输出在 frontend/test-results/，按 .gitignore 不提交。

复验请按 README 在本地创建独立测试库，使用同一组命令运行；待办和边界见 [原型交接指南](06-prototype-handoff.md)。
