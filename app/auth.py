import os
import jwt

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import (
    hash_password,
    verify_password,
    create_access_token,
)


router = APIRouter(prefix="/api/auth", tags=["用户认证"])


class UserCreate(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_]+$",
    )
    password: str = Field(min_length=8, max_length=128)


class UserPublic(BaseModel):
    id: int
    username: str


@router.post("/register", status_code=201, response_model=UserPublic)
def register_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
):
    existing = db.scalar(
        select(User).where(User.username == payload.username)
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="用户名已存在",
        )

    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
    )

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()

        # MySQL 重复值错误，处理同时注册同名账号的情况。
        if exc.orig.args[0] == 1062:
            raise HTTPException(
                status_code=409,
                detail="用户名已存在",
            ) from exc

        raise HTTPException(
            status_code=500,
            detail="注册失败",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="注册失败",
        ) from exc

    # 不返回密码或密码哈希。
    return {
        "id": user.id,
        "username": user.username,
    }

class UserLogin(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class TokenPublic(BaseModel):
    access_token: str
    token_type: str


@router.post("/login", response_model=TokenPublic)
def login_user(
    payload: UserLogin,
    db: Session = Depends(get_db),
):
    user = db.scalar(
        select(User).where(User.username == payload.username)
    )

    if user is None or not verify_password(
        payload.password,
        user.hashed_password,
    ):
        raise HTTPException(
            status_code=401,
            detail="用户名或密码错误",
        )

    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
    }

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=401,
        detail="未登录或登录凭证已失效",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    secret_key = os.getenv("JWT_SECRET_KEY")
    if not secret_key or len(secret_key.encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET_KEY 未正确配置")

    try:
        payload = jwt.decode(
            credentials.credentials,
            secret_key,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        raise unauthorized from exc

    user = db.get(User, user_id)

    if user is None:
        raise unauthorized

    return user


@router.get("/me", response_model=UserPublic)
def read_current_user(
    current_user: User = Depends(get_current_user),
):
    return {
        "id": current_user.id,
        "username": current_user.username,
    }