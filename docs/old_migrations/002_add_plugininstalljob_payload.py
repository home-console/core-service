"""
Migration: Add payload JSON column to plugin_install_jobs
Date: 2025-12-22
"""
import asyncpg
import asyncio
import os


async def migrate_up():
    db_url = os.getenv("DATABASE_URL", "postgresql://home:homepass@postgres:5432/home_console")
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "")
    parts = db_url.split("@")
    user_pass = parts[0].split(":")
    host_db = parts[1].split("/")
    host_port = host_db[0].split(":")
    conn = await asyncpg.connect(
        user=user_pass[0],
        password=user_pass[1],
        host=host_port[0],
        port=int(host_port[1]) if len(host_port) > 1 else 5432,
        database=host_db[1]
    )
    try:
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'plugin_install_jobs' 
                AND column_name = 'payload'
            )
        """)
        if not exists:
            await conn.execute("""
                ALTER TABLE plugin_install_jobs
                ADD COLUMN payload JSON
            """)
            print("✅ Added payload column to plugin_install_jobs")
        else:
            print("ℹ️  Column payload already exists")
    finally:
        await conn.close()


async def migrate_down():
    db_url = os.getenv("DATABASE_URL", "postgresql://home:homepass@postgres:5432/home_console")
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "")
    parts = db_url.split("@")
    user_pass = parts[0].split(":")
    host_db = parts[1].split("/")
    host_port = host_db[0].split(":")
    conn = await asyncpg.connect(
        user=user_pass[0],
        password=user_pass[1],
        host=host_port[0],
        port=int(host_port[1]) if len(host_port) > 1 else 5432,
        database=host_db[1]
    )
    try:
        await conn.execute("""
            ALTER TABLE plugin_install_jobs
            DROP COLUMN IF EXISTS payload
        """)
        print("✅ Removed payload column from plugin_install_jobs")
    finally:
        await conn.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "down":
        asyncio.run(migrate_down())
    else:
        asyncio.run(migrate_up())
