"""
Migration: Add runtime_mode column to plugins table
Date: 2025-12-22
"""
import asyncpg
import asyncio
import os


async def migrate_up():
    """Add runtime_mode column to plugins table"""
    db_url = os.getenv("DATABASE_URL", "postgresql://homeuser:homepass@postgres:5432/homedb")
    # Parse connection string
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
        # Check if column exists
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'plugins' 
                AND column_name = 'runtime_mode'
            )
        """)
        
        if not exists:
            await conn.execute("""
                ALTER TABLE plugins 
                ADD COLUMN runtime_mode VARCHAR(32)
            """)
            print("✅ Added runtime_mode column to plugins table")
        else:
            print("ℹ️  Column runtime_mode already exists")
    
    finally:
        await conn.close()


async def migrate_down():
    """Remove runtime_mode column from plugins table"""
    db_url = os.getenv("DATABASE_URL", "postgresql://homeuser:homepass@postgres:5432/homedb")
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
            ALTER TABLE plugins 
            DROP COLUMN IF EXISTS runtime_mode
        """)
        print("✅ Removed runtime_mode column from plugins table")
    
    finally:
        await conn.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "down":
        asyncio.run(migrate_down())
    else:
        asyncio.run(migrate_up())
