import getpass
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import requests


ROOT = Path(__file__).resolve().parent.parent
CASES_FILE = ROOT / "evals" / "cases.json"
OUTPUT_DIR = ROOT / "outputs" / "rag_eval"

BASE_URL = "http://127.0.0.1:8003"
KB_ID = 4
LIMIT = 10  # 首次只验证一道题，不要马上改成全部。


def main():
    cases_bytes = CASES_FILE.read_bytes()
    dataset = json.loads(cases_bytes.decode("utf-8-sig"))
    cases = dataset["cases"][:LIMIT]

    if not cases:
        raise SystemExit("没有可运行的评测题目。")

    with requests.Session() as client:
        client.trust_env = False

        username = input("RAG 用户名：").strip()
        password = getpass.getpass("密码（输入时不显示）：")

        response = client.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": username, "password": password},
            timeout=(5, 30),
        )
        del password

        if response.status_code != 200:
            raise SystemExit(f"登录失败，HTTP {response.status_code}")

        client.headers["Authorization"] = (
            f"Bearer {response.json()['access_token']}"
        )

        response = client.get(
            f"{BASE_URL}/api/knowledge-bases/{KB_ID}",
            timeout=(5, 30),
        )
        response.raise_for_status()
        library = response.json()

        if library["name"] != "RAG评测_基线_v1":
            raise SystemExit("知识库名称不符，停止评测，请检查 KB_ID。")

        response = client.get(
            f"{BASE_URL}/api/knowledge-bases/{KB_ID}/documents",
            params={"page": 1, "size": 20},
            timeout=(5, 30),
        )
        response.raise_for_status()
        documents = response.json()

        if (
            documents["total"] != 1
            or len(documents["items"]) != 1
            or documents["items"][0]["original_name"] != dataset["source"]
        ):
            raise SystemExit("评测库应只有一份指定手册，请检查文档。")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        print(f"\n知识库：{library['name']}（ID：{KB_ID}）")
        print(f"即将发送 {len(cases)} 次真实问答请求。")
        print("可能产生模型费用，并写入问答历史；不自动重试问答请求。")

        if input("确认运行请输入 RUN：").strip() != "RUN":
            print("已取消，没有发送问答请求。")
            return

        report = {
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "base_url": BASE_URL,
            "knowledge_base": library,
            "documents": documents["items"],
            "dataset_sha256": hashlib.sha256(cases_bytes).hexdigest(),
            "measurement": "client_end_to_end_seconds",
            "results": [],
        }

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
        path = OUTPUT_DIR / f"current_{stamp}_{uuid4().hex[:8]}.json"

        # 先创建报告，确保路径可写；即使中断也尽量保留已完成结果。
        with path.open("x", encoding="utf-8") as output:
            try:
                for case in cases:
                    question = f"{dataset['scope']}：{case['question']}"
                    record = {
                        "id": case["id"],
                        "question": question,
                        "answerable": case["answerable"],
                        "expected_points": case["expected_points"],
                        "request_ok": False,
                        "manual_answer_correct": None,
                        "manual_citations_supported": None,
                    }

                    started = time.perf_counter()

                    try:
                        response = client.post(
                            f"{BASE_URL}/api/knowledge-bases/{KB_ID}/chat",
                            json={"question": question},
                            timeout=(5, 150),
                        )
                        record["http_status"] = response.status_code
                        response.raise_for_status()
                        data = response.json()

                        if (
                            data.get("knowledge_base_id") != KB_ID
                            or not isinstance(data.get("answer"), str)
                            or not data["answer"].strip()
                        ):
                            raise ValueError("问答响应格式异常")

                        record["answer"] = data["answer"]
                        record["sources"] = data.get("sources", [])
                        record["citations"] = data.get("citations", [])
                        record["expected_document_retrieved"] = (
                            dataset["source"] in record["sources"]
                        )
                        record["request_ok"] = True

                    except (requests.RequestException, ValueError, KeyError) as exc:
                        record["error_type"] = type(exc).__name__

                    finally:
                        record["elapsed_seconds"] = round(
                            time.perf_counter() - started, 3
                        )
                        report["results"].append(record)

                    status = "成功，答案待人工核对" if record["request_ok"] else "失败"
                    print(
                        f"第 {case['id']} 题：{status}，"
                        f"耗时 {record['elapsed_seconds']} 秒"
                    )

                    if not record["request_ok"]:
                        print("已停止后续请求，请先排查失败原因。")
                        break

            finally:
                json.dump(report, output, ensure_ascii=False, indent=2)

        print(f"\n报告位置：{path}")
        print("请求成功不等于答案正确，请核对回答及引用片段。")


if __name__ == "__main__":
    main()