import argparse
import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import ApiToken, User
from app.security import create_token


async def create_user(email: str, timezone_name: str) -> None:
    async with SessionLocal() as session:
        existing = await session.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise SystemExit("A user with that email already exists")
        user = User(email=email, timezone=timezone_name)
        session.add(user)
        await session.commit()
        print(f"Created user {user.email} ({user.id})")


async def create_api_token(email: str, name: str) -> None:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            raise SystemExit("User not found")
        raw_token, token_hash = create_token()
        session.add(ApiToken(user_id=user.id, name=name, token_hash=token_hash))
        await session.commit()
        print(raw_token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Macro tracker administration CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    user_parser = subparsers.add_parser("create-user")
    user_parser.add_argument("--email", required=True)
    user_parser.add_argument("--timezone", default=get_settings().default_timezone)
    token_parser = subparsers.add_parser("create-token")
    token_parser.add_argument("--email", required=True)
    token_parser.add_argument("--name", required=True)
    args = parser.parse_args()
    if args.command == "create-user":
        asyncio.run(create_user(args.email, args.timezone))
    else:
        asyncio.run(create_api_token(args.email, args.name))


if __name__ == "__main__":
    main()
