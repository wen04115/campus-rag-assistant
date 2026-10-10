from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.rag import KNOWLEDGE_DIR, ask, ask_stream, rebuild_index

load_dotenv()
app = FastAPI(title="Campus RAG Demo", version="1.0.0")
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@app.get("/", include_in_schema=False)
def homepage():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/upload")   #上传接口 
async def upload_knowledge(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择文件")

    filename = Path(file.filename).name
    suffix = Path(filename).suffix.lower()

    if suffix not in {".txt", ".md"}:
        raise HTTPException(
            status_code=400,
            detail="只支持 .txt 和 .md 文件",
        )

    try:
        content = await file.read()
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="文件必须是 UTF-8 编码",
        ) from exc

    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    target_path = KNOWLEDGE_DIR / filename
    target_path.write_text(text, encoding="utf-8")

    return {
        "filename": filename,
        "message": "上传成功，请点击建立 / 重建索引",
    }

@app.post("/api/index")
def index_knowledge():
    try:
        return rebuild_index()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/chat")
def chat(payload: Question):
    try:
        return ask(payload.question)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post("/api/chat/stream")
def chat_stream(payload: Question):
    try:
        return StreamingResponse(
            ask_stream(payload.question),
            media_type="text/plain; charset=utf-8",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc