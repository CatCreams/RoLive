import asyncio
import os
import time
import httpx
import uvicorn
import tiktok

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
API_KEY      = os.environ.get("API_KEY", "tiktok-reactive-gift-queue-129DJJ")
UNIVERSE_ID  = "82169529818788"

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
    tiktok.connect(username)
    return {"ok": True}

@app.post("/session/stop", dependencies=[Depends(auth)])
def session_stop():
    tiktok.disconnect()
    return {"ok": True}

@app.get("/events/poll", dependencies=[Depends(auth)])
def events_poll(limit: int = 100):
    return tiktok.poll(min(limit, 200))

@app.get("/api/dashboard")
async def dashboard_data():
    roblox_playing = 0
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"https://games.roblox.com/v1/games?universeIds={UNIVERSE_ID}")
            data = r.json()
            roblox_playing = data["data"][0].get("playing", 0)
    except:
        pass
    return {
        "tiktok": tiktok.status(),
        "roblox": {
            "universeId": UNIVERSE_ID,
            "playing": roblox_playing,
            "url": "https://www.roblox.com/games/82169529818788",
        },
        "uptime": int(time.time()),
    }

@app.get("/api/events")
async def public_events():
    return tiktok.peek(50)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, loop="asyncio")