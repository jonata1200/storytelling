from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import (
    hash_password,
    normalize_email,
    validate_strong_password,
    verify_password,
)
from app.projects.models import User


def display_name_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0]
    pieces = [piece for piece in local_part.replace(".", " ").replace("_", " ").split() if piece]
    return " ".join(piece.capitalize() for piece in pieces) or email


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    normalized_email = normalize_email(email)
    result = await session.execute(select(User).where(User.email == normalized_email))
    return result.scalars().first()


async def register_user(
    session: AsyncSession,
    email: str,
    password: str,
    display_name: str | None = None,
) -> User:
    normalized_email = normalize_email(email)
    validate_strong_password(password, normalized_email)
    if await get_user_by_email(session, normalized_email) is not None:
        raise ValueError("Este e-mail ja está cadastrado.")
    cleaned_display_name = str(display_name or "").strip() or display_name_from_email(
        normalized_email
    )
    user = User(
        email=normalized_email,
        display_name=cleaned_display_name[:120],
        password_hash=hash_password(password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError("Este e-mail ja está cadastrado.") from exc
    await session.refresh(user)
    return user


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    try:
        user = await get_user_by_email(session, email)
    except ValueError:
        return None
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user
