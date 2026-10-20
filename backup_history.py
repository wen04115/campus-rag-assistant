import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parent
database = root / "data" / "chat_history.db"

if not database.is_file():
    raise FileNotFoundError(f"找不到历史数据库：{database}")

output_dir = root / "outputs"
output_dir.mkdir(exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
backup = output_dir / f"chat_history_backup_{timestamp}.db"

# 独占创建，避免覆盖已有备份。
with backup.open("xb"):
    pass

with (
    closing(sqlite3.connect(
        database.as_uri() + "?mode=ro",
        uri=True,
    )) as source,
    closing(sqlite3.connect(backup)) as target,
):
    source.backup(target)

    check = target.execute("PRAGMA quick_check").fetchone()[0]
    if check != "ok":
        raise RuntimeError(f"备份检查失败：{check}")

    count = target.execute(
        "SELECT COUNT(*) FROM chat_history"
    ).fetchone()[0]

print(f"备份检查通过，共 {count} 条历史记录")
print(f"备份位置：{backup}")