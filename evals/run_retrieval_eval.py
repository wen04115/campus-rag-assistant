"""Evaluate an existing KB index locally, without generating answers."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from uuid import uuid4


def normalize(text):
    return "".join(text.split())


def supports(case, content, metadata):
    return metadata.get("source") == case["expected_document"] and all(
        normalize(point) in normalize(content)
        for point in case["expected_evidence"]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True, help="Owner of the evaluation KB")
    parser.add_argument("--dataset", type=Path,
                        default=Path(__file__).with_name("retrieval_cases_v1.json"),
                        help="Path to a retrieval evaluation JSON dataset")
    args = parser.parse_args()
    dataset_path = args.dataset
    raw = dataset_path.read_bytes()
    dataset = json.loads(raw.decode("utf-8-sig"))
    cases = dataset["cases"]
    kb_id, k = dataset["knowledge_base_id"], dataset["top_k"]
    if not cases or k != 4:
        raise ValueError("Expected nonempty cases and the application's top_k=4")
    for case in cases:
        if not case["expected_evidence"] or not all(case["expected_evidence"]):
            raise ValueError(f"Missing gold evidence: {case['id']}")

    sys.path.insert(0, str(Path.cwd()))
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from langchain_chroma import Chroma
    from app.database import engine
    from app.models import KnowledgeBase, KnowledgeDocument, User
    from app.rag import VECTOR_DIR, _embeddings

    with Session(engine) as db:
        kb = db.scalar(select(KnowledgeBase).join(
            User, User.id == KnowledgeBase.user_id
        ).where(KnowledgeBase.id == kb_id, User.username == args.username))
        if kb is None or kb.name != dataset["knowledge_base_name"]:
            raise ValueError("KB ID, name or owner does not match; stopped")
        collection = kb.index_collection
        if not collection or not re.fullmatch(rf"kb_{kb_id}_[0-9a-f]{{32}}", collection):
            raise ValueError("Missing or unexpected index collection; stopped")
        document_names = dict(db.execute(select(
            KnowledgeDocument.id, KnowledgeDocument.original_name
        ).where(KnowledgeDocument.knowledge_base_id == kb_id)).all())

    expected_names = {case["expected_document"] for case in cases}
    if len(document_names) != 6 or set(document_names.values()) != expected_names:
        raise ValueError("Expected exactly the six evaluation documents; stopped")

    started = time.perf_counter()
    embeddings = _embeddings()
    model_load_seconds = time.perf_counter() - started
    store = Chroma(
        collection_name=collection,
        embedding_function=embeddings,
        persist_directory=str(VECTOR_DIR),
        create_collection_if_not_exists=False,
    )
    corpus = store.get(where={"knowledge_base_id": kb_id}, include=["documents", "metadatas"])
    rows = sorted([
        {"id": chunk_id, "content": content, "metadata": metadata}
        for chunk_id, content, metadata in zip(
            corpus["ids"], corpus["documents"], corpus["metadatas"], strict=True
        )
    ], key=lambda row: row["id"])
    if len(rows) <= k:
        raise ValueError("Corpus must contain more chunks than top_k")
    for row in rows:
        meta = row["metadata"]
        if (meta.get("knowledge_base_id") != kb_id
                or document_names.get(meta.get("document_id")) != meta.get("source")):
            raise ValueError("Index metadata does not match the KB's documents")
    for case in cases:
        if not any(supports(case, row["content"], row["metadata"]) for row in rows):
            raise ValueError(f"Gold evidence not found in any complete chunk: {case['id']}")

    # Warm up the local model and index; this query is excluded from metrics.
    started = time.perf_counter()
    store.similarity_search("检索评测预热", k=k, filter={"knowledge_base_id": kb_id})
    warmup_seconds = time.perf_counter() - started
    results = []
    for case in cases:
        started = time.perf_counter()
        matched = store.similarity_search(
            case["question"], k=k, filter={"knowledge_base_id": kb_id}
        )
        seconds = time.perf_counter() - started
        candidates = []
        for rank, doc in enumerate(matched, 1):
            if (doc.metadata.get("knowledge_base_id") != kb_id
                    or document_names.get(doc.metadata.get("document_id")) != doc.metadata.get("source")):
                raise ValueError("Retrieved a chunk outside the validated document set")
            candidates.append({"rank": rank, "content": doc.page_content,
                               "metadata": doc.metadata,
                               "supports_expected_evidence": supports(case, doc.page_content, doc.metadata)})
        first_rank = next((item["rank"] for item in candidates
                           if item["supports_expected_evidence"]), None)
        results.append({**case, "first_relevant_rank": first_rank,
                        "elapsed_seconds": seconds, "candidates": candidates})
        print(f"{case['id']}: first relevant rank={first_rank}, {seconds:.3f}s", flush=True)

    elapsed = [item["elapsed_seconds"] for item in results]
    count = len(results)
    metrics = {
        "questions": count,
        "hit_at_1": sum(item["first_relevant_rank"] == 1 for item in results) / count,
        "hit_at_4": sum(item["first_relevant_rank"] is not None for item in results) / count,
        "mrr_at_4": sum(1 / item["first_relevant_rank"]
                        if item["first_relevant_rank"] else 0 for item in results) / count,
        "median_seconds": statistics.median(elapsed), "max_seconds": max(elapsed),
    }
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "dataset_name": dataset["name"], "purpose": dataset["purpose"],
        "knowledge_base_id": kb_id, "knowledge_base_name": dataset["knowledge_base_name"],
        "collection": collection, "top_k": k, "chunk_count": len(rows),
        "embedding_model": os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
        "device": "cpu", "model_load_seconds": model_load_seconds,
        "warmup_seconds": warmup_seconds,
        "measurement": "warm local query embedding + Chroma search; not HTTP or answer latency",
        "relevance_rule": "exact source filename and all gold phrases in one chunk; whitespace ignored",
        "corpus": rows, "metrics": metrics, "results": results,
    }
    output = Path("/reports")
    if not output.is_dir():
        raise ValueError("Mount the report directory at /reports")
    path = output / f"retrieval_{datetime.now(UTC):%Y%m%d_%H%M%SZ}_{uuid4().hex[:8]}.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"Report: {path}")


if __name__ == "__main__":
    main()
