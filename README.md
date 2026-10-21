# Campus RAG：个人知识库问答助手

面向学习资料的本地演示项目：账号登录 → 私有知识库 → 上传文档 → 建立索引 → 流式问答和来源引用 → 历史记录。

本项目尚不是可直接暴露公网的生产系统。开发环境统一使用后端 `8002`；旧共享 API 已返回 410，不能继续使用旧版共享前端。

## 已实现

- JWT 登录、密码哈希、账号注册接口；页面刷新后验证并恢复当前标签页会话，不保存密码。
- 按账号隔离的知识库创建、列表、重命名和删除。文档未清空时拒绝删除知识库。
- UTF-8 TXT / Markdown / 文字版 PDF 上传、分页列表、删除；单文件不超过 10 MiB。
- 每个知识库使用独立 Chroma 集合；文档变化使索引失效，重建成功后再切换指向。
- 普通问答与 NDJSON 真流式问答，展示来源、页码、文档 ID 和检索片段。
- MySQL 持久化问答历史：保存完整回答，分页查询当前用户当前知识库的记录。
- 历史是当时的回答/引用快照；不会自动作为后续问题的上下文，也不是当前文档仍存在的证明。
- 删除知识库时，通过数据库外键级联删除该库历史。旧 SQLite 历史不自动归属给任何用户。
- GitHub Actions：隔离后端测试、前端 API 测试/静态检查/构建、临时 MySQL 迁移与外键检查。
- 离线索引维护工具，默认仅预览，不自动清理集合。

## 技术与目录

Python 3.12、FastAPI、SQLAlchemy / Alembic、MySQL、LangChain、Chroma、React、Vite。
聊天模型通过 OpenAI-compatible 接口调用；嵌入模型在本地 CPU 运行，首次真实建索引需要下载模型。

- `app/auth.py`、`security.py`：账号、密码哈希和 JWT。
- `app/knowledge_bases.py`、`documents.py`：归属检查和文档管理。
- `app/kb_index.py`、`knowledge_index.py`：构建和切换私有索引。
- `app/knowledge_chat.py`、`knowledge_history.py`：问答、流式事件和历史。
- `frontend/src/AccountApp.jsx`：当前页面入口；`DocumentPanel.jsx` 和 `HistoryPanel.jsx`：问答及历史。
- `migrations/`：MySQL 版本迁移，禁止用 create_all 代替业务迁移。
- `data/documents/`、`data/vector_store/`：上传文件和向量。
- `outputs/`：本地生成物、临时文件、可控缓存；不提交到 Git。
- `tests/`：内存数据库/模拟模型测试；`verify_mysql.py` 仅允许在 CI 临时数据库运行。

## 本地开发（Windows PowerShell）

保留现有 D 盘 checkout。新安装时，在项目内创建虚拟环境，不在 C 盘创建环境：

```powershell
cd D:\codex_create\2026-09-09\ai-python-rag-python-api-langchain
New-Item -ItemType Directory -Force outputs\test-tmp, outputs\pip-cache, outputs\npm-cache | Out-Null
$env:TEMP = (Resolve-Path outputs\test-tmp).Path
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = (Resolve-Path outputs\pip-cache).Path
$env:npm_config_cache = (Resolve-Path outputs\npm-cache).Path
$env:HF_HOME = Join-Path (Get-Location).Path "outputs\huggingface"

# 已有可用 Python 环境时，不需要重新安装。
D:\Python312\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

仅首次且尚无 `.env` 时复制 `.env.example`，不要覆盖现有配置。设置 MySQL、聊天服务和随机 JWT 密钥（至少 32 字节），不要提交真实密钥。

MySQL 数据库必须是独立的 `rag_platform`，连接账号需有该库的建表/读写权限；不要指向另一个任务管理项目的数据库。

迁移之前备份数据库，再检查和升级：

```powershell
D:\Python312\python.exe -m alembic current
D:\Python312\python.exe -m alembic upgrade head
D:\Python312\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

如果使用上面新建的虚拟环境，把命令中的 Python 换为 `.\.venv\Scripts\python.exe`。启动命令不带自动 reload，编辑后端后需要自行重启；不要误杀其他服务。

另一个终端启动前端（环境变量仅对设置它的终端及子进程有效）：

```powershell
cd D:\codex_create\2026-09-09\ai-python-rag-python-api-langchain\frontend
$env:npm_config_cache = Join-Path (Split-Path (Get-Location).Path) "outputs\npm-cache"
npm ci
npm run dev
```

页面使用 Vite 实际打印的地址（通常 localhost:5173），接口文档：<http://127.0.0.1:8002/docs>。
通过 Swagger 注册自己的演示账号，登录响应不代表 Swagger 已授权；Authorize 只填写令牌，不加额外引号或重复 Bearer。

## 自动检查

```powershell
# 项目根目录；使用隔离数据库和模拟模型，不调用真实聊天服务。
D:\Python312\python.exe tests/run_unit.py

cd frontend
npm run lint
npm test
npm run build
```

`npm run lint` 检查当前活跃入口及组件，不包含保留的旧共享 App.jsx；前端单元测试检查请求封装，不等于完整浏览器 E2E。
`test_upload.py` / `test_pdf_upload.py` 是旧 8001 服务的历史集成测试，不属于当前离线测试入口。

CI 的 MySQL job 使用独立临时容器，不读取你的真实 .env，不需要真实模型密钥。云端新的检查必须提交推送后才能确认，不以本地结果替代。

## Docker 本地演示

Dockerfile 会构建 React 并由 FastAPI 同源提供页面；无需再开 Vite，不经过会缓冲流式输出的反向代理。
Compose 连接已有宿主机 MySQL，不新建或覆盖你的业务数据库。

1. 先确认 Docker Desktop 的磁盘镜像在 D 盘、D 盘空间足够。构建会下载镜像和依赖，本项目不会自动执行构建。
2. 停止所有共用当前 `data/` 向量目录的本机/旧 Docker 服务，避免同时写 Chroma。备份 MySQL 和 `data/`。
3. 检查 .env。容器连接宿主机用 `host.docker.internal`；Linux 或远程 MySQL 可设置 `DOCKER_MYSQL_HOST`。MySQL 用户的 host 授权和防火墙必须允许该连接。
4. 在项目根目录手动执行：

```powershell
docker compose config --quiet
docker compose build
docker compose run --rm backend python -m alembic upgrade head
docker compose up -d
docker compose logs --tail 100 backend
```

页面和文档分别是 <http://127.0.0.1:8003> 和 <http://127.0.0.1:8003/docs>。
端口仅绑定回环，避免替换旧 8001 / 本机 8002 服务；`APP_PORT` 可覆盖宿主机端口。
`data/`、模型缓存和容器临时目录绑定到当前 D 盘项目；Docker 自身镜像位置仍由 Docker Desktop 管理。
健康检查只验证 HTTP 进程，不能证明数据库、模型或索引可用。不执行自动迁移，避免启动时意外修改业务库。
`docker compose down` 停止本项目容器，不要随意删除数据目录。此配置用于本地演示，不是公网生产部署模板。

## 索引维护：必须停服，默认预览

每次重建使用新集合。失败的构建、旧版本集合和失效指向可能留下未引用集合；这是保留旧索引而不冒险在线删除的代价。

先停止所有使用该向量目录的 API、建索引任务和容器，再备份 MySQL 与向量目录，然后运行：

```powershell
D:\Python312\python.exe -m app.index_cleanup
# 核对候选后才执行实际删除，不能在后台仍有构建任务时运行。
D:\Python312\python.exe -m app.index_cleanup --apply --confirm-stopped
```

工具只处理严格匹配 `kb_<正整数>_<32位UUID>` 且数据库未引用的集合；保留当前有效集合、旧共享 intern_rag 和未知集合。
预览也应在停服状态做。标志只是操作人员的确认，不是程序能自动证明所有其他进程都停止。
删除不可从页面撤销，恢复要依赖备份。Chroma 的底层文件未必立即缩小；不要手工删数据库/向量碎片文件。

## 检索评测与验证

基于 6 份模拟制度文档，构建两批共 24 道检索评测问题，
覆盖制度细节、口语改写及相似制度混淆场景。
使用固定的本地向量模型与 Top-K=4 配置，核验候选片段是否包含预期证据。

### 评测结果

- 基础题集（12 题）：Hit@1 为 100%，Hit@4 为 100%。
- 补充题集（12 题）：Hit@1 为 91.7%，Hit@4 为 100%，MRR@4 为 0.9583。

### 案例分析

补充题集中，一道实习生报销问题的正确证据排在第二位。
随后进行网页单题验证，最终回答正确，且展示的检索片段包含对应原文。

### 评测边界

本次评测仅覆盖小规模、人工构造的模拟制度数据，
不代表真实业务或大规模知识库上的整体效果。
检索命中不等于最终回答正确；网页验证仅覆盖上述单题。

运行步骤、指标定义及耗时口径见 [评测说明](evals/README.md)。

## 验收与限制

详见 [验收清单](docs/acceptance.md)。主要边界：

- 不支持扫描图片 PDF / OCR；不支持自动网页检索。
- 知识库列表及文档列表仅显示最近 20 条，暂不支持分页。
- 问答历史支持分页。文档列表与问答历史支持展开 / 收起。
- 普通/流式回答保存成功不保证客户端一定收到最终响应。网络中断后先检查历史，不自动重试，避免重复调用/保存。
- 本地取消请求不保证上游模型立即停止计费；流式部分文字可能已经到达客户端。
- 文档变化会使索引失效；不保证多进程高并发构建与回答的完备一致性。单实例演示，不设置多 worker。
- sessionStorage 中的令牌可被同源脚本读取；无 refresh token、服务端即时撤销、登录限流或公网 TLS 配置。令牌约 30 分钟有效，退出页面不等于撤销已泄露的 JWT。
- 向量检索不保证回答真实、完整；应核对原文和引用。恶意文档可能包含提示注入，不能把模型输出用于高风险自动决策。
- 直接依赖已固定到当前环境版本，但不等于所有传递依赖均已锁定。
