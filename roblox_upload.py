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
        print(f"[Cache] HIT memory @{username}: {memory_cache[username]!r}")
        return memory_cache[username]

    if HAS_PG and DATABASE_URL:
        try:
            db = await asyncpg.connect(DATABASE_URL)
            row = await db.fetchrow("SELECT asset_id FROM avatar_cache WHERE username = $1", username)
            await db.close()
            if row:
                print(f"[Cache] HIT db @{username}: {row['asset_id']!r}")
                memory_cache[username] = row["asset_id"]
                return row["asset_id"]
        except Exception as e:
            print(f"[DB] get failed: {e}")

    print(f"[Cache] MISS @{username}")
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
            print(f"[Cache] Saved to DB @{username}: {asset_id}")
        except Exception as e:
            print(f"[DB] save failed: {e}")


async def upload_avatar_to_roblox(username: str, image_data: bytes, content_type: str) -> str | None:
    print(f"[Upload] Called @{username} | image_data size: {len(image_data)} bytes")

    cached = await get_cached_asset(username)
    if cached:
        print(f"[Upload] Returning cached @{username}: {cached}")
        return cached

    api_key      = os.environ.get("ROBLOX_API_KEY", "")
    creator_id   = os.environ.get("ROBLOX_CREATOR_ID", "")
    creator_type = os.environ.get("ROBLOX_CREATOR_TYPE", "user")

    print(f"[Upload] Env check | api_key set: {bool(api_key)} | creator_id: {creator_id!r} | creator_type: {creator_type!r}")

    if not api_key or not creator_id:
        print(f"[Upload] ABORT — missing ROBLOX_API_KEY or ROBLOX_CREATOR_ID")
        return None

    creator_key = "groupId" if creator_type == "group" else "userId"

    try:
        async with httpx.AsyncClient(timeout=30) as c:
            request_body = {
                "assetType": "Image",
                "displayName": f"avatar_{username}",
                "description": "",
                "creationContext": {"creator": {creator_key: creator_id}}
            }
            print(f"[Upload] Sending POST to Roblox Assets API @{username} | body: {request_body}")

            r = await c.post(
                "https://apis.roblox.com/assets/v1/assets",
                headers={"x-api-key": api_key},
                data={"request": json.dumps(request_body)},
                files={"fileContent": (f"{username}.jpg", image_data, content_type)},
            )

            print(f"[Upload] POST response @{username}: status={r.status_code} body={r.text[:300]}")

            if not r.is_success:
                print(f"[Upload] FAILED @{username}: {r.status_code} {r.text}")
                return None

            resp_json = r.json()
            op_id = resp_json.get("operationId")
            print(f"[Upload] operationId @{username}: {op_id!r}")

            if not op_id:
                print(f"[Upload] No operationId — full response: {resp_json}")
                return None

            for attempt in range(15):
                await asyncio.sleep(3)
                poll = await c.get(
                    f"https://apis.roblox.com/assets/v1/operations/{op_id}",
                    headers={"x-api-key": api_key},
                )
                result = poll.json()
                print(f"[Upload] Poll {attempt+1}/15 @{username}: {result}")

                if result.get("done"):
                    asset_id = result.get("response", {}).get("assetId")
                    if not asset_id:
                        print(f"[Upload] done=true but no assetId — response: {result}")
                        return None
                    rbx = f"rbxassetid://{asset_id}"
                    await save_cached_asset(username, rbx)
                    print(f"[Upload] SUCCESS @{username}: {rbx}")
                    return rbx

            print(f"[Upload] TIMEOUT @{username} after 15 polls (45s)")
            return None

    except Exception as e:
        print(f"[Upload] EXCEPTION @{username}: {e}")
        return None


async def clear_cache_for_user(username: str):
    if username in memory_cache:
        del memory_cache[username]
        save_json_cache(memory_cache)

    if HAS_PG and DATABASE_URL:
        try:
            db = await asyncpg.connect(DATABASE_URL)
            await db.execute("DELETE FROM avatar_cache WHERE username = $1", username)
            await db.close()
            print(f"[Cache] Cleared @{username}")
        except Exception as e:
            print(f"[DB] clear failed: {e}")


async def clear_all_cache():
    memory_cache.clear()
    save_json_cache(memory_cache)

    if HAS_PG and DATABASE_URL:
        try:
            db = await asyncpg.connect(DATABASE_URL)
            await db.execute("DELETE FROM avatar_cache")
            await db.close()
            print(f"[Cache] All cleared")
        except Exception as e:
            print(f"[DB] clear all failed: {e}")