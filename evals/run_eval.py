import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parent.parent
CASES_FILE = ROOT / "evals" / "cases.json"
OUTPUT_DIR = ROOT / "outputs" / "rag_eval"
API_URL = "http://127.0.0.1:8001/api/chat"


if __name__ == "__main__":
    dataset = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    results = []

    with requests.Session() as client:
        # 本机接口不走系统代理
        client.trust_env = False

        for case in dataset["cases"]:
            question = f"{dataset['scope']}：{case['question']}"

            record = {
                "id": case["id"],
                "question": question,
                "answerable": case["answerable"],
                "expected_points": case["expected_points"],
                "request_ok": False,
            }

            started = time.perf_counter()

            try:
                response = client.post(
                    API_URL,
                    json={"question": question},
                    timeout=(5, 120),
                )
                record["http_status"] = response.status_code

                if response.status_code != 200:
                    raise ValueError(
                        f"HTTP {response.status_code}，请检查后端日志"
                    )

                data = response.json()

                record["answer"] = data["answer"]
                record["sources"] = data.get("sources", [])
                record["citations"] = data.get("citations", [])
                record["expected_source_retrieved"] = (
                    dataset["source"] in record["sources"]
                )
                record["request_ok"] = True

                print(f"第 {case['id']} 题：请求成功，答案待核对")

            except (requests.RequestException, ValueError, KeyError) as error:
                record["error"] = str(error)
                print(f"第 {case['id']} 题：请求失败")

            record["elapsed_seconds"] = round(
                time.perf_counter() - started, 2
            )
            results.append(record)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%fZ")
    report_file = OUTPUT_DIR / f"eval_{timestamp}.json"

    with report_file.open("x", encoding="utf-8") as file:
        json.dump(
            {
                "expected_source": dataset["source"],
                "results": results,
            },
            file,
            ensure_ascii=False,
            indent=2,
        )

    successful = sum(record["request_ok"] for record in results)
    print(f"\n请求成功：{successful}/{len(results)}")
    print(f"报告位置：{report_file}")