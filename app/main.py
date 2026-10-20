import json
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.document_loader import load_document_bytes
from app.rag import KNOWLEDGE_DIR, ask, ask_stream, delete_source_from_index, rebuild_index

load_dotenv()
app = FastAPI(title="Campus RAG Demo", version="1.0.0")
STATIC_DIR = Path(__file__).resolve().parent / "static"
ROOT = Path(__file__).resolve().parent.parent
HISTORY_DB = ROOT / "data" / "chat_history.db"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def init_history_database():
    HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(HISTORY_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                sources TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def save_chat_history(question: str, result: dict):
    sources_json = json.dumps(
        result.get("sources", []),
        ensure_ascii=False,
    )

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(HISTORY_DB) as conn:
        conn.execute(
            """
            INSERT INTO chat_history (question, answer, sources, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                question,
                result["answer"],
                sources_json,
                created_at,
            ),
        )


init_history_database()

class Question(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    source: str | None = Field(default=None, min_length=1, max_length=255)


@app.get("/", include_in_schema=False)
def homepage():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_knowledge(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择文件")

    filename = Path(file.filename).name
    suffix = Path(filename).suffix.lower()

    if suffix not in {".txt", ".md", ".pdf"}:
        raise HTTPException(
            status_code=400,
            detail="只支持 .txt、.md 和文字版 PDF 文件",
        )

    # 单个文件最多 10 MiB，超出时不继续读取
    max_size = 10 * 1024 * 1024
    content = await file.read(max_size + 1)

    if len(content) > max_size:
        raise HTTPException(
            status_code=413,
            detail="文件不能超过 10 MiB",
        )

    # 先验证编码或 PDF 是否能解析，失败时不保存
    try:
        load_document_bytes(content, filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    target_path = KNOWLEDGE_DIR / filename

    try:
        # xb：以二进制新建，禁止覆盖同名文件
        with target_path.open("xb") as target:
            target.write(content)
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail="同名文件已存在，请先删除旧文件再上传",
        ) from exc

    return {
        "filename": filename,
        "message": "上传成功，请点击建立 / 重建索引",
    }

@app.get("/api/files")
def get_knowledge_files():
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    files = [
        {
            "name": path.name,
            "size": path.stat().st_size,
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }
        for path in KNOWLEDGE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in {".txt", ".md", ".pdf"}
    ]

    return sorted(files, key=lambda item: item["updated_at"], reverse=True)


@app.delete("/api/files/{filename}")
def delete_knowledge_file(filename: str):
    safe_filename = Path(filename).name
    suffix = Path(safe_filename).suffix.lower()

    if safe_filename != filename or suffix not in {".txt", ".md", ".pdf"}:
        raise HTTPException(status_code=400, detail="不支持删除该文件")

    target_path = KNOWLEDGE_DIR / safe_filename
    if not target_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        target_path.unlink()
        index_updated = delete_source_from_index(safe_filename)
        return {
            "filename": safe_filename,
            "message": "文件已删除，向量索引已同步更新" if index_updated else "文件已删除，尚未建立索引",
            "index_updated": index_updated,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"删除文件失败：{exc}") from exc


@app.post("/api/index")
def index_knowledge():
    try:
        return rebuild_index()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.get("/api/history")
def get_history():
    try:
        with sqlite3.connect(HISTORY_DB) as conn:
            conn.row_factory = sqlite3.Row

            rows = conn.execute(
                """
                SELECT id, question, answer, sources, created_at
                FROM chat_history
                ORDER BY id DESC
                LIMIT 20
                """
            ).fetchall()

        return [
            {
                "id": row["id"],
                "question": row["question"],
                "answer": row["answer"],
                "sources": json.loads(row["sources"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"读取历史记录失败：{exc}",
        ) from exc

@app.post("/api/chat")
def chat(payload: Question):
    try:
        result = ask(payload.question, source=payload.source)

        save_chat_history(payload.question, result)

        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post("/api/chat/stream")
def chat_stream(payload: Question):
    try:
        return StreamingResponse(
            ask_stream(payload.question, source=payload.source),
            media_type="text/plain; charset=utf-8",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
