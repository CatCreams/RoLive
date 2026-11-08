import asyncio
import os
import httpx
import json
import time
import uuid

from dotenv import load_dotenv
load_dotenv()

from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, DisconnectEvent, GiftEvent, LikeEvent

try:
    from TikTokLive.events import FollowEvent
except ImportError:
    FollowEvent = None

try:
    from TikTokLive.events import RoomUserSeqEvent
except ImportError:
    RoomUserSeqEvent = None

try:
    from TikTokLive.events import CommentEvent
except ImportError:
    try:
        from TikTokLive.events import ChatEvent as CommentEvent
    except ImportError:
        CommentEvent = None


UNIVERSE_ID     = os.environ.get("UNIVERSE_ID", "")
ROBLOX_API_KEY  = os.environ.get("ROBLOX_API_KEY", "")
RAILWAY_URL     = os.environ.get("RAILWAY_URL", "https://rolive.up.railway.app")
MESSAGING_TOPIC = "TikTokEvents"
MAX_QUEUE       = 1000
PUSH_MAX_RETRY  = 3
PUSH_RETRY_WAIT = 2.0

event_queue: list = []
sessions: dict = {}
avatar_cache: dict = {}
avatar_image_cache: dict = {}

_queue_lock   = asyncio.Lock()
_session_lock = asyncio.Lock()


async def push_to_roblox(event: dict, attempt: int = 1):
    api_key     = os.environ.get("ROBLOX_API_KEY", "").strip()
    universe_id = os.environ.get("UNIVERSE_ID", "").strip()

    if not api_key or not universe_id:
        return

    try:
        async with httpx.AsyncClient(timeout=5) as c:
            resp = await c.post(
                f"https://apis.roblox.com/messaging-service/v1/universes/{universe_id}/topics/{MESSAGING_TOPIC}",
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={"message": json.dumps(event)},
            )

            if resp.status_code == 429 or resp.status_code >= 500:
                raise Exception(f"status={resp.status_code}")

            if resp.status_code >= 400:
                print(f"[Push] Error: {resp.status_code} {resp.text[:100]}")
                return

    except Exception as e:
        print(f"[Push] Attempt {attempt} failed: {e}")

        if attempt < PUSH_MAX_RETRY:
            await asyncio.sleep(PUSH_RETRY_WAIT * attempt)
            await push_to_roblox(event, attempt + 1)


async def _precache_avatar(uid: str, url: str, is_streamer: bool = False):
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as c:
            r = await c.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; RoLive/1.0)",
                "Referer": "https://www.tiktok.com/",
            })
            if r.is_success:
                content_type = r.headers.get("content-type", "image/jpeg")
                avatar_image_cache[uid] = (r.content, content_type)
                print(f"[Avatar] Pre-cached @{uid}")

                # Langsung pakai URL TikTok, tidak upload ke Roblox
                if is_streamer:
                    await push_to_roblox({
                        "type":           "streamer_connected",
                        "username":       uid,
                        "streamerAvatar": url,
                    })
            else:
                print(f"[Avatar] Fetch failed @{uid}: status={r.status_code}")
    except Exception as e:
        print(f"[Avatar] Pre-cache failed @{uid}: {e}")


def _extract_avatar(user_obj) -> str | None:
    if not user_obj:
        return None

    for attr in ("avatar_thumb", "avatar_medium", "avatar", "avatar_larger"):
        obj = getattr(user_obj, attr, None)
        if obj:
            urls = getattr(obj, "url_list", [])
            if urls:
                return urls[-1]

    return None


def _cache_avatar(user_obj):
    if not user_obj:
        return

    uid = (
        getattr(user_obj, "unique_id", "")
        or getattr(user_obj, "uniqueId", "")
        or ""
    ).lower().lstrip("@")

    if not uid or uid in avatar_cache:
        return

    url = _extract_avatar(user_obj)

    if url:
        avatar_cache[uid] = url
        print(f"[Avatar] Cached @{uid}: {url[:80]}")
        loop = asyncio.get_event_loop()
        loop.create_task(_precache_avatar(uid, url))


async def enqueue(username: str, type_: str, payload: dict):
    sess = sessions.get(username)

    if sess and sess.get("paused"):
        return

    event = {
        "eventId":   str(uuid.uuid4()),
        "type":      type_,
        "username":  username,
        "timestamp": int(time.time()),
        **payload,
    }

    async with _queue_lock:
        event_queue.append(event)
        if len(event_queue) > MAX_QUEUE:
            event_queue.pop(0)

    if username in sessions:
        sessions[username]["stats"][type_] = (
            sessions[username]["stats"].get(type_, 0) + 1
        )

    loop = asyncio.get_event_loop()
    loop.create_task(push_to_roblox(event))


async def _run(username: str):
    sess = sessions.get(username)

    if not sess:
        return

    client = TikTokLiveClient(unique_id=username)
    sess["client"] = client

    @client.on(ConnectEvent)
    async def on_connect(event):
        sess["connected"] = True
        sess["joined_at"] = time.time()
        print(f"[TikTok] Connected: @{username}")

        try:
            if client.room_info:
                owner = client.room_info.get("owner", {})

                avatar_url = None
                for key, list_key in [("avatarThumb", "urlList"), ("avatar_thumb", "url_list"), ("avatarMedium", "urlList")]:
                    obj = owner.get(key, {})
                    urls = obj.get(list_key, [])
                    if urls:
                        avatar_url = urls[-1]
                        break

                if avatar_url:
                    avatar_cache[username] = avatar_url
                    sess["profilePictureUrl"] = avatar_url
                    print(f"[Avatar] Got @{username}: {avatar_url[:80]}")

                    loop = asyncio.get_event_loop()
                    loop.create_task(_precache_avatar(username, avatar_url, is_streamer=True))

                cover_url = None
                for key, list_key in [("coverUrl", "urlList"), ("roomCover", "urlList")]:
                    obj = owner.get(key, {})
                    urls = obj.get(list_key, [])
                    if urls:
                        cover_url = urls[-1]
                        break

                if cover_url:
                    sess["coverUrl"] = cover_url

        except Exception as e:
            print(f"[Avatar] room_info error @{username}: {e}")

    @client.on(DisconnectEvent)
    async def on_disconnect(event):
        sess["connected"] = False
        print(f"[TikTok] Disconnected: @{username}")

    if RoomUserSeqEvent:
        @client.on(RoomUserSeqEvent)
        async def on_viewers(event):
            vc = getattr(event, "total", None)
            if vc is not None:
                sess["viewer_count"] = max(0, int(vc))

    @client.on(GiftEvent)
    async def on_gift(event):
        _cache_avatar(getattr(event, "user", None))

        if event.gift.streakable and not event.streaking:
            return

        sender_uid = (
            getattr(event.user, "unique_id", "") or ""
        ).lower().lstrip("@")

        gift_name = (
            getattr(event.gift, "name", None)
            or getattr(event.gift.info, "name", None)
            or "unknown"
        )

        gift_id = (
            getattr(event.gift, "id", None)
            or getattr(event.gift.info, "id", None)
            or "0"
        )

        # Ambil URL dari avatar_cache langsung
        sender_avatar = avatar_cache.get(sender_uid, "")

        await enqueue(
            username,
            "gift",
            {
                "giftId":       str(gift_id),
                "giftName":     gift_name,
                "count":        event.repeat_count or 1,
                "sender":       event.user.nickname or "unknown",
                "senderUid":    sender_uid,
                "senderAvatar": sender_avatar,
            },
        )

    @client.on(LikeEvent)
    async def on_like(event):
        _cache_avatar(getattr(event, "user", None))

        await enqueue(
            username,
            "like",
            {
                "count":  event.count or 1,
                "sender": event.user.nickname or "unknown",
            },
        )

    if FollowEvent:
        @client.on(FollowEvent)
        async def on_follow(event):
            _cache_avatar(getattr(event, "user", None))

            sender_uid = (
                getattr(event.user, "unique_id", "") or ""
            ).lower().lstrip("@")

            sender_avatar = avatar_cache.get(sender_uid, "")

            await enqueue(
                username,
                "follow",
                {
                    "sender":       getattr(event.user, "nickname", "unknown") or "unknown",
                    "senderUid":    sender_uid,
                    "senderAvatar": sender_avatar,
                },
            )

    if CommentEvent:
        @client.on(CommentEvent)
        async def on_comment(event):
            _cache_avatar(getattr(event, "user", None))

            msg = (
                getattr(event, "comment", None)
                or getattr(event, "message", None)
                or ""
            )

            sender = (
                getattr(event.user, "nickname", "unknown")
                if hasattr(event, "user")
                else "unknown"
            )

            sender_uid = (
                (getattr(event.user, "unique_id", "") or "").lower().lstrip("@")
                if hasattr(event, "user")
                else ""
            )

            sender_avatar = avatar_cache.get(sender_uid, "")

            await enqueue(
                username,
                "chat",
                {
                    "message":      msg,
                    "sender":       sender,
                    "senderUid":    sender_uid,
                    "senderAvatar": sender_avatar,
                },
            )

    try:
        await client.connect(fetch_room_info=True)
    except Exception as e:
        sess["connected"] = False
        print(f"[TikTok] Failed @{username}: {e}")


def connect(username: str):
    username = username.lstrip("@").lower()

    if username in sessions:
        existing = sessions[username]
        if (
            existing.get("connected")
            or (
                existing.get("task")
                and not existing["task"].done()
            )
        ):
            print(f"[TikTok] @{username} already active")
            return

    sessions[username] = {
        "client":            None,
        "connected":         False,
        "paused":            False,
        "task":              None,
        "stats":             {"gift": 0, "like": 0, "chat": 0, "follow": 0},
        "joined_at":         time.time(),
        "viewer_count":      None,
        "profilePictureUrl": None,
        "coverUrl":          None,
    }

    loop = asyncio.get_event_loop()
    task = loop.create_task(_run(username))
    sessions[username]["task"] = task


def pause(username: str) -> bool:
    sess = sessions.get(username.lstrip("@").lower())
    if not sess:
        return False
    sess["paused"] = True
    return True


def resume(username: str) -> bool:
    sess = sessions.get(username.lstrip("@").lower())
    if not sess:
        return False
    sess["paused"] = False
    return True


async def disconnect(username: str = None):
    async with _session_lock:
        targets = (
            [username.lstrip("@").lower()]
            if username
            else list(sessions.keys())
        )

        loop = asyncio.get_event_loop()

        for user in targets:
            sess = sessions.pop(user, None)
            if sess and sess.get("client"):
                loop.create_task(sess["client"].disconnect())


async def poll(limit: int = 100):
    async with _queue_lock:
        items = event_queue[:limit]
        del event_queue[:limit]
    return items


def peek(limit: int = 50):
    return list(event_queue[-limit:])


def list_sessions():
    result = []

    for user, sess in sessions.items():
        result.append({
            "username":          user,
            "connected":         sess["connected"],
            "paused":            sess.get("paused", False),
            "stats":             sess["stats"],
            "joined_at":         sess.get("joined_at"),
            "queueLength":       len([e for e in event_queue if e.get("username") == user]),
            "viewer_count":      sess.get("viewer_count"),
            "profilePictureUrl": f"{RAILWAY_URL}/api/avatar/{user}",
            "coverUrl":          sess.get("coverUrl"),
        })

    return result


def status():
    for user, sess in sessions.items():
        if sess["connected"]:
            return {
                "connected":   True,
                "paused":      sess.get("paused", False),
                "username":    user,
                "queueLength": len(event_queue),
            }

    return {
        "connected":   False,
        "paused":      False,
        "username":    None,
        "queueLength": len(event_queue),
    }