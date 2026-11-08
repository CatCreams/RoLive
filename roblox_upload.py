import os
import json
import asyncio
import httpx
from pathlib import Path

try:
    import asyncpg
    HAS_PG = True
except ImportError:
    HAS_PG = False

DATABASE_URL     = os.environ.get("DATABASE_URL", "")
ASSET_CACHE_FILE = Path("avatar_asset_cache.json")

def load_json_cache() -> dict:
    if ASSET_CACHE_FILE.exists():
        try:
            return json.loads(ASSET_CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_json_cache(cache: dict):
    try:
        ASSET_CACHE_FILE.write_text(json.dumps(cache))
    except Exception:
        pass

memory_cache: dict = load_json_cache()


async def init_db():
    if not HAS_PG or not DATABASE_URL:
        return
    try:
        db = await asyncpg.connect(DATABASE_URL)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS avatar_cache (
                username TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL
            )
        """)
        await db.close()
    except Exception as e:
        print(f"[DB] init failed: {e}")


async def get_cached_asset(username: str) -> str | None:
    if username in memory_cache:
        return memory_cache[username]

    if HAS_PG and DATABASE_URL:
        try:
            db = await asyncpg.connect(DATABASE_URL)
            row = await db.fetchrow("SELECT asset_id FROM avatar_cache WHERE username = $1", username)
            await db.close()
            if row:
                memory_cache[username] = row["asset_id"]
                return row["asset_id"]
        except Exception as e:
            print(f"[DB] get failed: {e}")

    return None


async def save_cached_asset(username: str, asset_id: str):
    memory_cache[username] = asset_id
    save_json_cache(memory_cache)

    if HAS_PG and DATABASE_URL:
        try:
            db = await asyncpg.connect(DATABASE_URL)
            await db.execute("""
                INSERT INTO avatar_cache (username, asset_id)
                VALUES ($1, $2)
                ON CONFLICT (username) DO NOTHING
            """, username, asset_id)
            await db.close()
        except Exception as e:
            print(f"[DB] save failed: {e}")


async def upload_avatar_to_roblox(username: str, image_data: bytes, content_type: str) -> str | None:
    cached = await get_cached_asset(username)
    if cached:
        return cached

    api_key      = os.environ.get("ROBLOX_API_KEY", "")
    creator_id   = os.environ.get("ROBLOX_CREATOR_ID", "")
    creator_type = os.environ.get("ROBLOX_CREATOR_TYPE", "user")

    if not api_key or not creator_id:
        print("[Upload] Missing ROBLOX_API_KEY or ROBLOX_CREATOR_ID")
        return None

    creator_key = "groupId" if creator_type == "group" else "userId"

    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                "https://apis.roblox.com/assets/v1/assets",
                headers={"x-api-key": api_key},
                data={"request": json.dumps({
                    "assetType": "Decal",
                    "displayName": f"avatar_{username}",
                    "description": "",
                    "creationContext": {"creator": {creator_key: creator_id}}
                })},
                files={"fileContent": (f"{username}.jpg", image_data, content_type)},
            )

            if not r.is_success:
                print(f"[Upload] Failed @{username}: {r.text}")
                return None

            op_id = r.json().get("operationId")

            for _ in range(10):
                await asyncio.sleep(2)
                poll = await c.get(
                    f"https://apis.roblox.com/assets/v1/operations/{op_id}",
                    headers={"x-api-key": api_key},
                )
                result = poll.json()
                if result.get("done"):
                    asset_id = result["response"]["assetId"]
                    rbx = f"rbxassetid://{asset_id}"
                    await save_cached_asset(username, rbx)
                    print(f"[Upload] Done @{username}: {rbx}")
                    return rbx

    except Exception as e:
        print(f"[Upload] Error @{username}: {e}")

    return None