"""Offline-only maintenance; dry-run by default. Never deletes document files."""
import argparse
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import engine
from app.models import KnowledgeBase
from app.rag import VECTOR_DIR


def active_collections(db: Session) -> set[str]:
    return set(db.scalars(
        select(KnowledgeBase.index_collection).where(
            KnowledgeBase.index_collection.is_not(None),
        )
    ).all())


def cleanup_candidates(names: list[str], active: set[str]) -> list[str]:
    # Only our UUID-named private collections; preserve shared/unknown collections.
    return sorted({
        name for name in names
        if re.fullmatch(r"kb_[1-9][0-9]*_[0-9a-f]{32}", name)
        and name not in active
    })


def clean_unused(client, db: Session, apply: bool = False) -> dict:
    names = [item if isinstance(item, str) else item.name for item in client.list_collections()]
    candidates = cleanup_candidates(names, active_collections(db))
    db.rollback()
    removed = []
    if apply:
        for name in candidates:
            # Recheck using a new transaction before each deletion.
            if name not in active_collections(db):
                client.delete_collection(name=name)
                removed.append(name)
            db.rollback()
    return {"candidates": candidates, "removed": removed}


def main():
    parser = argparse.ArgumentParser(description="停服维护：清理未引用的私有向量集合，默认仅预览")
    parser.add_argument("--apply", action="store_true", help="实际删除候选集合")
    parser.add_argument("--confirm-stopped", action="store_true", help="确认所有索引构建/问答进程已停止")
    args = parser.parse_args()
    if args.apply and not args.confirm_stopped:
        parser.error("实际清理前必须停止所有使用该向量目录的服务，并传入 --confirm-stopped")
    if not VECTOR_DIR.exists():
        print("没有向量目录，无需清理")
        return
    import chromadb
    client = chromadb.PersistentClient(path=str(VECTOR_DIR))
    with Session(engine) as db:
        result = clean_unused(client, db, apply=args.apply)
    print("预览候选：" if not args.apply else "已执行清理；候选：")
    for name in result["candidates"]:
        print(name)
    print(f"候选 {len(result['candidates'])} 个，实际删除 {len(result['removed'])} 个")
    print("集合删除不保证底层磁盘文件立即缩小；不要手动删除 Chroma 数据文件。")


if __name__ == "__main__":
    main()
