import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from dotenv import load_dotenv
from pwdlib import PasswordHash


# 当前文件位于 app 内，因此向上两级定位项目根目录。
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(user_id: int) -> str:
    secret_key = os.getenv("JWT_SECRET_KEY")

    if not secret_key or len(secret_key.encode("utf-8")) < 32:
        raise RuntimeError(
            "请在 RAG 项目的 .env 中配置至少 32 字节的 JWT_SECRET_KEY"
        )

    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }

    return jwt.encode(payload, secret_key, algorithm="HS256")