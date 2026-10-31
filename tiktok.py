"""
tiktok.py — Multi-session TikTok Live manager
"""

import asyncio
import os
import httpx
import json
import time
import uuid
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, DisconnectEvent, GiftEvent, LikeEvent

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
MESSAGING_TOPIC = "TikTokEvents"
MAX_QUEUE       = 1000
PUSH_MAX_RETRY  = 3
PUSH_RETRY_WAIT = 2.0

event_queue: list = []
sessions: dict    = {}
_queue_lock       = asyncio.Lock()
_session_lock     = asyncio.Lock()


def _extract(room, sess: dict):
    try:
        vc = (
            getattr(getattr(room, "user_count", None), "value", None)
            or getattr(getattr(room, "stats", None), "total_user", None)
            or getattr(room, "viewer_count", None)
        )
        if vc:
            sess["viewer_count"] = int(vc)
    except Exception:
        pass

    try:
        owner  = getattr(room, "owner", None)
        avatar = getattr(owner, "avatar_thumb", None) or getattr(owner, "avatar_medium", None)
        urls   = getattr(avatar, "url_list", [])
        if urls:
            sess["profile_picture_url"] = urls[-1]
    except Exception:
        pass

    try:
        cover = getattr(room, "cover", None)
        urls  = getattr(cover, "url_list", [])
        if urls:
            sess["cover_url"] = urls[-1]
    except Exception:
        pass


async def push_to_roblox(event: dict, attempt: int = 1):
    api_key     = os.environ.get("ROBLOX_API_KEY", "").strip()
    universe_id = os.environ.get("UNIVERSE_ID", "").strip()
    if not api_key or not universe_id:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            resp = await c.post(
                f"https://apis.roblox.com/messaging-service/v1/universes/{universe_id}/topics/{MESSAGING_TOPIC}",
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
                json={"message": json.dumps(event)},
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                raise Exception(f"status={resp.status_code}")
            if resp.status_code >= 400:
                print(f"[Push] Error: {resp.status_code}")
                return
    except Exception as e:
        if attempt < PUSH_MAX_RETRY:
            await asyncio.sleep(PUSH_RETRY_WAIT * attempt)
            await push_to_roblox(event, attempt + 1)


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
        sessions[username]["stats"][type_] = sessions[username]["stats"].get(type_, 0) + 1

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
        room = getattr(event, "room", None) or getattr(client, "room_info", None)
        if room:
            _extract(room, sess)

    @client.on(DisconnectEvent)
    async def on_disconnect(event):
        sess["connected"] = False
        print(f"[TikTok] Disconnected: @{username}")

    if RoomUserSeqEvent:
        @client.on(RoomUserSeqEvent)
        async def on_viewers(event):
            fields = {}
            for k in dir(event):
                if k.startswith("_"):
                    continue
                try:
                    v = getattr(event, k)
                    if isinstance(v, (int, float, str, bool)):
                        fields[k] = v
                except:
                    pass
            print(f"[DEBUG RoomUserSeq] @{username}: {fields}")
            vc = getattr(event, "viewer_count", None) or getattr(event, "total_user", None)
            if vc is not None:
                sess["viewer_count"] = max(0, int(vc))

    @client.on(GiftEvent)
    async def on_gift(event):
        if event.gift.streakable and not event.repeat_end:
            return
        await enqueue(username, "gift", {
            "giftId":   str(event.gift.id),
            "giftName": event.gift.name or "unknown",
            "count":    event.repeat_count or 1,
            "sender":   event.user.nickname or "unknown",
        })

    @client.on(LikeEvent)
    async def on_like(event):
        await enqueue(username, "like", {
            "count":  event.count or 1,
            "sender": event.user.nickname or "unknown",
        })

    if CommentEvent:
        @client.on(CommentEvent)
        async def on_comment(event):
            msg    = getattr(event, "comment", None) or getattr(event, "message", None) or ""
            sender = getattr(event.user, "nickname", "unknown") if hasattr(event, "user") else "unknown"
            await enqueue(username, "chat", {"message": msg, "sender": sender})

    try:
        await client.connect()
    except Exception as e:
        sess["connected"] = False
        print(f"[TikTok] Failed @{username}: {e}")


def connect(username: str):
    username = username.lstrip("@").lower()
    if username in sessions:
        existing = sessions[username]
        if existing.get("connected") or (existing.get("task") and not existing["task"].done()):
            print(f"[TikTok] @{username} already active")
            return
    sessions[username] = {
        "client":              None,
        "connected":           False,
        "paused":              False,
        "task":                None,
        "stats":               {"gift": 0, "like": 0, "chat": 0},
        "joined_at":           time.time(),
        "viewer_count":        None,
        "profile_picture_url": None,
        "cover_url":           None,
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
        targets = [username.lstrip("@").lower()] if username else list(sessions.keys())
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
            "profilePictureUrl": sess.get("profile_picture_url"),
            "coverUrl":          sess.get("cover_url"),
        })
    return result


def status():
    for user, sess in sessions.items():
        if sess["connected"]:
            return {"connected": True, "paused": sess.get("paused", False), "username": user, "queueLength": len(event_queue)}
    return {"connected": False, "paused": False, "username": None, "queueLength": len(event_queue)}