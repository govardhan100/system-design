import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from auth_service.models import Role, User


async def promote_admin(email: str) -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            user = await session.scalar(
                select(User)
                .options(selectinload(User.roles))
                .where(User.email == email.strip().lower())
            )
            admin_role = await session.scalar(select(Role).where(Role.name == "admin"))
            if user is None:
                raise ValueError("Create the account before promoting it to admin")
            if admin_role is None:
                raise ValueError("Admin role is missing; apply database migrations first")
            if admin_role not in user.roles:
                user.roles.append(admin_role)
                await session.commit()
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote an existing account to admin")
    parser.add_argument("email")
    arguments = parser.parse_args()
    asyncio.run(promote_admin(arguments.email))
    print(f"Admin role granted to {arguments.email.strip().lower()}")


if __name__ == "__main__":
    main()