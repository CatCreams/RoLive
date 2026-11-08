from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import re
import time
import base64
import httpx
import uvicorn
import tiktok

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from tiktok import avatar_image_cache

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY     = os.environ.get("API_KEY", "")
UNIVERSE_ID = os.environ.get("UNIVERSE_ID", "")

TIKTOK_CDN_RE = re.compile(r"^https://[a-zA-Z0-9\-]+\.tiktokcdn(?:-us|-eu|-sg|-jp)?\.com/")


def auth(request: Request):
    if request.headers.get("x-api-key") != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("dashboard.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/api/image-proxy")
async def image_proxy(url: str):
    if not url or not TIKTOK_CDN_RE.match(url):
        raise HTTPException(status_code=400, detail="URL tidak valid atau domain tidak diizinkan")
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as c:
            r = await c.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; RoLive/1.0)",
                "Referer":    "https://www.tiktok.com/",
            })
            if not r.is_success:
                raise HTTPException(status_code=502, detail="Gagal fetch gambar dari CDN")
            content_type = r.headers.get("content-type", "image/jpeg")
            return StreamingResponse(
                iter([r.content]),
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=300"},
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="Gagal menghubungi CDN TikTok")


async def _fetch_avatar_data(username: str):
    if username in avatar_image_cache:
        return avatar_image_cache[username]

    sess = tiktok.sessions.get(username)
    avatar_url = sess.get("profilePictureUrl") if sess else None
    avatar_url = avatar_url or tiktok.avatar_cache.get(username)

    if not avatar_url:
        return None, None

    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as c:
            r = await c.get(avatar_url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; RoLive/1.0)",
                "Referer":    "https://www.tiktok.com/",
            })
            if r.is_success:
                content_type = r.headers.get("content-type", "image/jpeg")
                avatar_image_cache[username] = (r.content, content_type)
                return r.content, content_type
    except Exception:
        pass

    return None, None


@app.get("/api/avatar/{username}")
async def get_avatar(username: str):
    username = username.lower().lstrip("@")
    data, content_type = await _fetch_avatar_data(username)
    if not data:
        raise HTTPException(status_code=404, detail="Avatar tidak ditemukan")
    return StreamingResponse(
        iter([data]),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/avatar/{username}/base64")
async def get_avatar_base64(username: str):
    username = username.lower().lstrip("@")
    data, content_type = await _fetch_avatar_data(username)
    if not data:
        raise HTTPException(status_code=404, detail="Avatar tidak ditemukan")
    return {
        "base64":      base64.b64encode(data).decode(),
        "contentType": content_type,
    }


@app.post("/session/start", dependencies=[Depends(auth)])
async def session_start(request: Request):
    body = await request.json()
    username = body.get("username")
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    async with tiktok._session_lock:
        tiktok.connect(username)
    return {"ok": True, "username": username}


@app.post("/session/stop", dependencies=[Depends(auth)])
async def session_stop(request: Request):
    try:
        body = await request.json()
        username = body.get("username")
    except Exception:
        username = None
    await tiktok.disconnect(username)
    return {"ok": True}


@app.post("/session/pause", dependencies=[Depends(auth)])
async def session_pause(request: Request):
    body = await request.json()
    username = body.get("username")
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    ok = tiktok.pause(username)
    if not ok:
        raise HTTPException(status_code=404, detail="Session tidak ditemukan")
    return {"ok": True, "paused": True}


@app.post("/session/resume", dependencies=[Depends(auth)])
async def session_resume(request: Request):
    body = await request.json()
    username = body.get("username")
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    ok = tiktok.resume(username)
    if not ok:
        raise HTTPException(status_code=404, detail="Session tidak ditemukan")
    return {"ok": True, "paused": False}


@app.get("/events/poll", dependencies=[Depends(auth)])
async def events_poll(limit: int = 100):
    return await tiktok.poll(min(limit, 200))


@app.get("/api/events")
async def public_events():
    return tiktok.peek(100)


@app.get("/api/dashboard")
async def dashboard_data():
    roblox_playing = 0
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"https://games.roblox.com/v1/games?universeIds={UNIVERSE_ID}"
            )
            if r.status_code == 200:
                data = r.json()
                roblox_playing = data["data"][0].get("playing", 0)
    except Exception:
        pass

    return {
        "sessions": tiktok.list_sessions(),
        "tiktok":   tiktok.status(),
        "roblox": {
            "universeId": UNIVERSE_ID,
            "playing":    roblox_playing,
            "url":        f"https://www.roblox.com/games/{UNIVERSE_ID}",
        },
        "uptime": int(time.time()),
    }


@app.get("/api/sessions")
async def api_sessions():
    return tiktok.list_sessions()


@app.post("/api/roblox/lookup")
async def roblox_lookup(request: Request):
    body = await request.json()
    username = body.get("username", "")
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                "https://users.roblox.com/v1/usernames/users",
                json={"usernames": [username], "excludeBannedUsers": True},
                headers={"Content-Type": "application/json"},
            )
            if not r.is_success:
                raise HTTPException(status_code=502, detail="Roblox API error")
            data = r.json()
            user = data.get("data", [None])[0]
            if not user:
                raise HTTPException(status_code=404, detail="Username Roblox tidak ditemukan")

            avatar = None
            try:
                img = await c.get(
                    f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user['id']}&size=150x150&format=Png&isCircular=false"
                )
                if img.is_success:
                    avatar = img.json()["data"][0]["imageUrl"]
            except Exception:
                pass

            return {"id": user["id"], "name": user["name"], "avatar": avatar}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gagal menjangkau Roblox: {e}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, loop="asyncio")