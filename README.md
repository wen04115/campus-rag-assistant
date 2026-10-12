# 校园知识库助手

面向本地校园资料的 RAG 知识库问答应用，支持文档上传、向量检索、来源引用和历史记录。

用户可以上传 `.txt` 或 `.md` 文件，点击建立索引后，再根据上传的资料提问。系统会先从资料里找相关内容，再让大模型根据这些内容回答。

## 核心功能

- 支持上传 UTF-8 编码的 TXT、Markdown 文档
- 基于文本切片、向量化和 Chroma 完成语义检索
- 基于检索片段生成回答，并展示来源文件和引用内容
- 对知识库外的问题返回无依据提示
- 使用 SQLite 保存问答历史记录

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

frontend/
  src/App.jsx   React 页面主要代码
  src/index.css 页面样式
  vite.config.js Vite 代理配置

data/
  knowledge/    上传的知识库文件
  vector_store/ Chroma 建好的向量索引
  chat_history.db 聊天历史数据库

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

## 项目截图
### 上传并建立向量索引

![上传并建立向量索引](./rag-upload-and-index.png)

### 问答历史与来源引用

![问答历史与来源引用](./rag-history-with-sources.png)

### FastAPI 接口文档

![FastAPI 接口文档](./rag-api-docs.png)

### 怎么启动
启动后端
先进入项目根目录：
cd campus-rag-assistant

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

## 设计说明
- 前端通过 Vite 代理将 `/api` 请求转发至 FastAPI，避免开发环境跨域问题。
- 上传文件后需建立或重建向量索引，才可参与后续语义检索。
- API Key 使用 `.env` 管理，并通过 `.gitignore` 防止提交敏感配置。
