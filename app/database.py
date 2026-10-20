import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

database_url = URL.create(
    drivername="mysql+pymysql",
    username=os.environ["MYSQL_USER"],
    password=os.environ["MYSQL_PASSWORD"],
    host=os.environ["MYSQL_HOST"],
    port=int(os.getenv("MYSQL_PORT", "3306")),
    database=os.environ["MYSQL_DATABASE"],
    query={"charset": "utf8mb4"},
)

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 5},
)


def get_db():
    with Session(engine) as session:
        yield session


if __name__ == "__main__":
    with engine.connect() as connection:
        database_name = connection.execute(
            text("SELECT DATABASE()")
        ).scalar_one()
        result = connection.execute(text("SELECT 1")).scalar_one()

    print(f"已连接数据库：{database_name}")
    print(f"连接检查结果：{result}")