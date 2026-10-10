# Campus RAG：应届生 AI + Python 全栈作品

一个可以本地跑通的企业知识库问答项目。它将本地 Markdown/TXT 文档切分、向量化并存入 Chroma，再由大模型根据检索到的上下文作答。适合用来展示 Python 后端、LLM API、向量数据库、LangChain 与前端交互的完整链路。

## 技术栈

- **FastAPI**：提供 REST API 和静态网页
- **LangChain**：文本切分、提示词、模型调用流程编排
- **DeepSeek API（OpenAI-compatible）**：负责 Chat LLM 生成
- **BGE-small-zh 本地模型**：负责 Embedding，无需第二个 API Key
- **Chroma**：本地持久化向量数据库
- **原生 HTML/CSS/JS**：聊天界面，避免前端框架干扰面试重点

## 快速开始

要求：Python 3.10+，以及一个兼容 OpenAI SDK 的 API Key。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`，填入新创建的 DeepSeek `OPENAI_API_KEY`。保留 `OPENAI_BASE_URL=https://api.deepseek.com`，不要在行首加 `#`；`CHAT_MODEL=deepseek-v4-flash` 即可。首次建立索引时会下载 BGE 中文向量模型，之后会使用本地缓存。

```powershell
uvicorn app.main:app --reload
```

浏览器打开 http://127.0.0.1:8000，先点“建立 / 重建索引”，再提问。API 文档在 http://127.0.0.1:8000/docs。

## RAG 链路（面试时这样讲）

`知识文件 → RecursiveCharacterTextSplitter → Embedding API → Chroma → 相似度检索 Top-4 → Prompt（上下文+问题）→ Chat LLM → 答案+来源`

1. 文档切块（500 字符，80 字符重叠）解决长文无法直接嵌入、边界语义丢失的问题。
2. 本地 BGE Embedding 将文本和问题映射为同一向量空间；Chroma 按相似度找回最相关的 4 个片段。
3. Prompt 要求模型只能根据检索上下文作答，减少幻觉，并把命中的文件名返回给页面，方便追溯。
4. 索引与问答拆成两个 API：`POST /api/index` 负责离线建库，`POST /api/chat` 负责在线检索生成。这是生产化的基本分层。

## 可继续迭代（简历亮点）

- 加入 PDF/Word 解析、上传文件与异步任务队列
- 用 Reranker 重排召回结果，增加引用片段和评分
- 增加对话历史、用户权限与多知识库隔离
- 用 LangSmith 观测 token、延迟与命中质量；构建问答集做 RAGAS 评估
- Docker 化并部署到云服务器

## 项目结构

```text
app/             FastAPI、RAG 服务和网页
data/knowledge/  可替换的知识库源文件
data/vector_store/  运行后自动生成的 Chroma 数据
```
