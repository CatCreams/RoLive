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
        s = sessions[username]["stats"]
        s[type_] = s.get(type_, 0) + 1

    loop = asyncio.get_event_loop()
    loop.create_task(push_to_roblox(event))


def _extract_room_info(client: TikTokLiveClient, sess: dict):
    """
    Ekstrak viewer count, profile picture, dan cover/thumbnail dari room info client.
    TikTokLive library menyimpan data room di client.room_info setelah connect.
    """
    try:
        room_info = getattr(client, "room_info", None) or {}

        # --- Viewer count ---
        # Coba beberapa path yang mungkin ada di room_info
        viewers = (
            room_info.get("user_count", {}).get("value")
            or room_info.get("stats", {}).get("total_user")
            or room_info.get("viewer_count")
            or None
        )
        if viewers is not None:
            try:
                sess["viewer_count"] = int(viewers)
            except (TypeError, ValueError):
                pass

        # --- Profile picture ---
        owner = room_info.get("owner", {}) or {}
        avatar_thumb = (
            owner.get("avatar_thumb", {}) or {}
        )
        avatar_urls = avatar_thumb.get("url_list", [])
        if avatar_urls:
            sess["profile_picture_url"] = avatar_urls[-1]  # ambil resolusi tertinggi
        elif owner.get("avatar_larger", {}).get("url_list"):
            sess["profile_picture_url"] = owner["avatar_larger"]["url_list"][-1]

        # --- Cover / thumbnail live ---
        cover = room_info.get("cover", {}) or {}
        cover_urls = cover.get("url_list", [])
        if cover_urls:
            sess["cover_url"] = cover_urls[-1]
        else:
            # fallback: share_info thumbnail
            share_info = room_info.get("share_info", {}) or {}
            thumb = share_info.get("cover", {}) or {}
            thumb_urls = thumb.get("url_list", [])
            if thumb_urls:
                sess["cover_url"] = thumb_urls[-1]

    except Exception as e:
        print(f"[RoomInfo] Gagal ekstrak room info: {e}")


async def _poll_room_info(username: str):
    """
    Poll viewer count setiap 10 detik selama session aktif.
    Dipanggil sebagai background task setelah connect.
    """
    while True:
        await asyncio.sleep(10)
        sess = sessions.get(username)
        if not sess or not sess.get("connected"):
            break
        client = sess.get("client")
        if client:
            _extract_room_info(client, sess)


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
        # Ekstrak room info pertama kali saat connect
        _extract_room_info(client, sess)
        # Mulai background polling viewer count
        loop = asyncio.get_event_loop()
        loop.create_task(_poll_room_info(username))

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
        "client":              None,
        "connected":           False,
        "paused":              False,
        "task":                None,
        "stats":               {"gift": 0, "like": 0, "chat": 0},
        "joined_at":           time.time(),
        "viewer_count":        None,  # diisi saat connect
        "profile_picture_url": None,  # diisi saat connect
        "cover_url":           None,  # diisi saat connect
    }
    loop = asyncio.get_event_loop()
    task = loop.create_task(_run(username))
    sessions[username]["task"] = task


def pause(username: str) -> bool:
    username = username.lstrip("@").lower()
    sess = sessions.get(username)
    if not sess:
        return False
    sess["paused"] = True
    print(f"[TikTok] Paused: @{username}")
    return True


def resume(username: str) -> bool:
    username = username.lstrip("@").lower()
    sess = sessions.get(username)
    if not sess:
        return False
    sess["paused"] = False
    print(f"[TikTok] Resumed: @{username}")
    return True


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
            "username":           user,
            "connected":          sess["connected"],
            "paused":             sess.get("paused", False),
            "stats":              sess["stats"],
            "joined_at":          sess.get("joined_at"),
            "queueLength":        len([e for e in event_queue if e.get("username") == user]),
            # Field baru — viewer count & gambar
            "viewer_count":       sess.get("viewer_count"),
            "profilePictureUrl":  sess.get("profile_picture_url"),
            "coverUrl":           sess.get("cover_url"),
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
    return {"connected": False, "paused": False, "username": None, "queueLength": len(event_queue)}