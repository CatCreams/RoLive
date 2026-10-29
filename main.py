import asyncio
import os
import time
import httpx
import uvicorn
import tiktok

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse

app = FastAPI()
API_KEY     = os.environ.get("API_KEY", "")
UNIVERSE_ID = os.environ.get("UNIVERSE_ID", "")


def auth(request: Request):
    if request.headers.get("x-api-key") != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("dashboard.html", "r", encoding="utf-8") as f:
        return f.read()


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
            data = r.json()
            roblox_playing = data["data"][0].get("playing", 0)
    except:
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, loop="asyncio")