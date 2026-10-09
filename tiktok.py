import asyncio
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, DisconnectEvent, GiftEvent, LikeEvent, CommentEvent

event_queue = []
client = None
username = None
connected = False
_task = None

def enqueue(type, payload):
    event_queue.append({"type": type, **payload})
    if len(event_queue) > 500:
        event_queue.pop(0)

async def _run(user):
    global client, connected

    client = TikTokLiveClient(unique_id=user)

    @client.on(ConnectEvent)
    async def on_connect(event):
        global connected
        connected = True
        print(f"[TikTok] Connected: @{user}")

    @client.on(DisconnectEvent)
    async def on_disconnect(event):
        global connected
        connected = False
        print(f"[TikTok] Disconnected")

    @client.on(GiftEvent)
    async def on_gift(event):
        if event.gift.streakable and not event.repeat_end:
            return
        enqueue("gift", {
            "giftId":   str(event.gift.id),
            "giftName": event.gift.name or "unknown",
            "count":    event.repeat_count or 1,
            "sender":   event.user.nickname or "unknown",
        })

    @client.on(LikeEvent)
    async def on_like(event):
        enqueue("like", {
            "count":  event.count or 1,
            "sender": event.user.nickname or "unknown",
        })

    @client.on(CommentEvent)
    async def on_comment(event):
        enqueue("chat", {
            "message": event.comment or "",
            "sender":  event.user.nickname or "unknown",
        })

    try:
        await client.connect()
    except Exception as e:
        connected = False
        print(f"[TikTok] Failed: {e}")

def connect(user):
    global username, _task, connected
    username = user
    connected = False

    loop = asyncio.get_event_loop()

    if _task and not _task.done():
        _task.cancel()

    _task = loop.create_task(_run(user))

def disconnect():
    global client, username, connected, _task
    if client:
        asyncio.get_event_loop().create_task(client.disconnect())
    client = None
    username = None
    connected = False

def poll(limit=100):
    items = event_queue[:limit]
    del event_queue[:limit]
    return items

def status():
    return {"connected": connected, "username": username, "queueLength": len(event_queue)}