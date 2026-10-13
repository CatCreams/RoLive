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
    from TikTokLive.events import CommentEvent
    print("[TikTok] CommentEvent import OK")
except ImportError:
    try:
        from TikTokLive.events import ChatEvent as CommentEvent
        print("[TikTok] ChatEvent import OK (alias CommentEvent)")
    except ImportError:
        CommentEvent = None
        print("[TikTok] WARNING: CommentEvent/ChatEvent tidak ditemukan!")

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


async def push_to_roblox(event: dict, attempt: int = 1):
    api_key     = os.environ.get("ROBLOX_API_KEY", "").strip()
    universe_id = os.environ.get("UNIVERSE_ID", "").strip()
    if not api_key or not universe_id:
        print("[Push] SKIP — ROBLOX_API_KEY atau UNIVERSE_ID tidak di-set")
        return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            resp = await c.post(
                f"https://apis.roblox.com/messaging-service/v1/universes/{universe_id}/topics/{MESSAGING_TOPIC}",
                headers={
                    "x-api-key":    api_key,
                    "Content-Type": "application/json",
                },
                json={"message": json.dumps(event)},
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                raise Exception(f"status={resp.status_code}")
            if resp.status_code >= 400:
                print(f"[Push] Error permanent: {resp.status_code} {resp.text}")
                return
            print(f"[Push] OK type={event.get('type')} id={event.get('eventId','?')}")
    except Exception as e:
        if attempt < PUSH_MAX_RETRY:
            print(f"[Push] Retry {attempt}/{PUSH_MAX_RETRY}: {e}")
            await asyncio.sleep(PUSH_RETRY_WAIT * attempt)
            await push_to_roblox(event, attempt + 1)
        else:
            print(f"[Push] Gagal setelah {PUSH_MAX_RETRY} retry: {e}")


async def enqueue(username: str, type_: str, payload: dict):
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
        s = sessions[username]["stats"]
        s[type_] = s.get(type_, 0) + 1

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

    @client.on(DisconnectEvent)
    async def on_disconnect(event):
        sess["connected"] = False
        print(f"[TikTok] Disconnected: @{username}")

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
            await enqueue(username, "chat", {
                "message": msg,
                "sender":  sender,
            })

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
        "client":    None,
        "connected": False,
        "task":      None,
        "stats":     {"gift": 0, "like": 0, "chat": 0},
        "joined_at": time.time(),
    }
    loop = asyncio.get_event_loop()
    task = loop.create_task(_run(username))
    sessions[username]["task"] = task


async def disconnect(username: str = None):
    async with _session_lock:
        targets = [username.lstrip("@").lower()] if username else list(sessions.keys())
        loop = asyncio.get_event_loop()
        for user in targets:
            sess = sessions.pop(user, None)
            if sess and sess.get("client"):
                loop.create_task(sess["client"].disconnect())
            print(f"[TikTok] Disconnected: @{user}")


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
            "username":    user,
            "connected":   sess["connected"],
            "stats":       sess["stats"],
            "joined_at":   sess.get("joined_at"),
            "queueLength": len([e for e in event_queue if e.get("username") == user]),
        })
    return result


def status():
    for user, sess in sessions.items():
        if sess["connected"]:
            return {
                "connected":   True,
                "username":    user,
                "queueLength": len(event_queue),
            }
    return {"connected": False, "username": None, "queueLength": len(event_queue)}