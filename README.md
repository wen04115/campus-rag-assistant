# 文档知识库问答助手

这是一个简单的 RAG 知识库问答项目。

用户可以上传 `.txt` 或 `.md` 文件，点击建立索引后，再根据上传的资料提问。系统会先从资料里找相关内容，再让大模型根据这些内容回答。

## 这个项目能做什么

- 上传 TXT、Markdown 文件
- 把文件切成多个小段，建立向量索引
- 根据知识库内容回答问题
- 显示回答参考了哪些文件和片段
- 对知识库里没有的问题，提示“没有找到相关信息”
- 保存聊天历史记录
- 刷新网页后还能看到以前的提问记录
- 查看和删除已上传文件
- 使用 Docker 运行后端

## 用到的技术

- React：做前端页面
- Vite：启动 React 开发环境
- FastAPI：写后端接口
- LangChain：处理 RAG 流程
- Chroma：保存文本向量，查找相似内容
- DeepSeek API：生成最终回答
- SQLite：保存聊天记录

## 项目结构

```text
app/
  main.py       后端接口，比如上传、建索引、提问、读取历史记录
  rag.py        文档切分、向量检索、调用大模型
  static/       之前写的原生 HTML 页面

frontend/
  src/App.jsx   React 页面主要代码
  src/index.css 页面样式
  vite.config.js Vite 代理配置

data/
  knowledge/    上传的知识库文件
  vector_store/ Chroma 建好的向量索引
  chat_history.db 聊天历史数据库
```  

## RAG 流程

### 上传文件
→ 保存到 data/knowledge
→ 把文件切成多个片段
→ 把片段转成向量
→ 保存到 Chroma

### 用户提问

→ Chroma 找最相似的几个片段
→ 把片段和问题一起发给大模型
→ 返回回答、来源文件和引用片段


### 本地启动
本地后端和 Docker 后端选择一种启动，两者默认都使用 8001 端口，不要同时启动

本地启动后端
先进入项目根目录：
cd D:\codex_create\2026-09-09\ai-python-rag-python-api-langchain

第一次运行时安装 Python 依赖：
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

复制环境变量文件：
Copy-Item .env.example .env

打开 .env，填写自己的 API Key：
OPENAI_API_KEY=你的真实密钥
OPENAI_BASE_URL=https://api.deepseek.com
CHAT_MODEL=deepseek-v4-flash

### 启动后端：
uvicorn app.main:app --reload --port 8001
后端接口文档地址：
http://127.0.0.1:8001/docs

### 启动前端
新开一个终端：
cd D:\codex_create\2026-09-09\ai-python-rag-python-api-langchain\frontend
npm install
npm run dev

浏览器打开：
http://localhost:5173

## 使用 Docker 启动后端

先在项目根目录配置好 `.env`，然后构建镜像：

```powershell
docker build -t document-rag-assistant .
```

第一次运行：

```powershell
docker run --name document-rag -p 127.0.0.1:8001:8001 --env-file .env -v "${PWD}/data:/app/data" document-rag-assistant
```

看到启动成功后，访问 http://127.0.0.1:8001/health，返回 `{"status":"ok"}` 即正常。

在终端按 Ctrl + C 停止。下次启动直接执行：

```powershell
docker start -a document-rag
```

数据保存在本机项目的 `data` 目录。React 前端单独启动：

```powershell
cd frontend
npm run dev
```

### 使用方法
1. 上传一个 .txt 或 .md 文件。
2. 点击“建立 / 重建索引”。
3. 在聊天框输入问题。
4. 查看回答、来源和引用片段。
5. 在历史记录区域查看之前问过的问题。

### 接口
- POST /api/upload：上传文件
- POST /api/index：建立索引
- POST /api/chat：普通问答
- POST /api/chat/stream：流式问答
- GET /api/history：读取聊天历史
- GET /health：检查后端是否启动
- GET /api/files：查看文件列表
- DELETE /api/files/{filename}：删除文件及对应的向量片段

### 我遇到的问题
- 前端和后端端口不同，开发时用 Vite 代理把 /api 请求转发到 FastAPI。
- 上传文件后不能直接提问，还需要先建立索引。
- 刷新网页后聊天气泡会清空，所以用 SQLite 保存历史记录。
- .env 里有真实 API Key，所以要加入 .gitignore，不能提交到 Git。  