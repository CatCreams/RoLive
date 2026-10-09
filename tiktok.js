const { WebcastPushConnection } = require('tiktok-live-connector');

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

    connection = new WebcastPushConnection(user, {
        processInitialData: false,
        enableExtendedGiftInfo: true,
        sessionId: process.env.TIKTOK_SESSION_ID || '',
    });

    connection.connect()
        .then(() => {
            connected = true;
            console.log(`[TikTok] Connected: @${user}`);
        })
        .catch(err => console.error(`[TikTok] Failed:`, err.message));

    connection.on('gift', (data) => {
        if (data.giftType === 1 && !data.repeatEnd) return;
        enqueue('gift', {
            giftId:   String(data.giftId),
            giftName: data.giftName || 'unknown',
            count:    data.repeatCount || 1,
            sender:   data.nickname || 'unknown',
        });
    });

    connection.on('like', (data) => {
        enqueue('like', {
            count:  data.likeCount || 1,
            sender: data.nickname || 'unknown',
        });
    });

    connection.on('chat', (data) => {
        enqueue('chat', {
            message: data.comment || '',
            sender:  data.nickname || 'unknown',
        });
    });

    connection.on('disconnected', () => {
        connected = false;
        console.warn(`[TikTok] Disconnected — retry in 10s`);
        setTimeout(() => { if (username) connect(username); }, 10000);
    });

    connection.on('error', (err) => {
        console.error('[TikTok] Error:', err.message);
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