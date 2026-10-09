const { TikTokLiveConnection, WebcastEvent, ControlEvent } = require('tiktok-live-connector');

const eventQueue = [];
let connection   = null;
let username     = null;
let connected    = false;

function enqueue(type, payload) {
    eventQueue.push({ type, ts: Date.now(), ...payload });
    if (eventQueue.length > 500) eventQueue.shift();
}

function connect(user) {
    if (connection) connection.disconnect();
    username  = user;
    connected = false;

    connection = new TikTokLiveConnection(user, {
        processInitialData: false,
        enableExtendedGiftInfo: true,
        signApiKey: process.env.EULER_API_KEY || '',
        sessionId: process.env.TIKTOK_SESSION_ID || '',
    });

    connection.connect()
        .then(() => {
            connected = true;
            console.log(`[TikTok] Connected: @${user}`);
        })
        .catch(err => console.error(`[TikTok] Failed:`, err.message));

    connection.on(WebcastEvent.GIFT, (data) => {
        if (data.giftDetails?.giftType === 1 && !data.repeatEnd) return;
        enqueue('gift', {
            giftId:   String(data.giftId),
            giftName: data.giftDetails?.giftName || 'unknown',
            count:    data.repeatCount || 1,
            sender:   data.user?.nickname || 'unknown',
        });
    });

    connection.on(WebcastEvent.LIKE, (data) => {
        enqueue('like', {
            count:  data.likeCount || 1,
            sender: data.user?.nickname || 'unknown',
        });
    });

    connection.on(WebcastEvent.CHAT, (data) => {
        enqueue('chat', {
            message: data.comment || '',
            sender:  data.user?.nickname || 'unknown',
        });
    });

    connection.on(ControlEvent.DISCONNECTED, () => {
        connected = false;
        console.warn(`[TikTok] Disconnected — retry in 10s`);
        setTimeout(() => { if (username) connect(username); }, 10000);
    });

    connection.on(ControlEvent.ERROR, ({ info, exception }) => {
        console.error('[TikTok] Error:', info, exception?.message);
    });
}

function disconnect() {
    if (connection) connection.disconnect();
    connection = null;
    username   = null;
    connected  = false;
}

function poll(limit = 100) {
    return eventQueue.splice(0, limit);
}

function status() {
    return { connected, username, queueLength: eventQueue.length };
}

module.exports = { connect, disconnect, poll, status };