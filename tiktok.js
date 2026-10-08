const { WebcastPushConnection } = require('tiktok-live-connector');

const giftQueue = [];
let tiktokConnection = null;
let currentUsername = null;

function connect(username) {
    if (tiktokConnection) tiktokConnection.disconnect();

    currentUsername = username;
    tiktokConnection = new WebcastPushConnection(username, {
        processInitialData: false,
        enableExtendedGiftInfo: true,
        sessionId: process.env.TIKTOK_SESSION_ID || '',
    });

    tiktokConnection.connect()
        .then(() => console.log(`[TikTok] Connected: @${username}`))
        .catch(err => console.error(`[TikTok] Connect failed:`, err.message));

    tiktokConnection.on('gift', (data) => {
        console.log(`[RAW] id:${data.giftId} name:${data.giftName} type:${data.giftType} repeatEnd:${data.repeatEnd} sender:${data.nickname}`);

        if (data.giftType === 1 && !data.repeatEnd) return;

        giftQueue.push({
            giftId: String(data.giftId),
            giftName: data.giftName,
            count: data.repeatCount || 1,
            sender: data.nickname || 'unknown',
        });

        console.log(`[Gift] ${data.nickname}: ${data.giftName} (id:${data.giftId}) x${data.repeatCount}`);
    });

    tiktokConnection.on('disconnected', () => {
        console.warn(`[TikTok] Disconnected — reconnect in 10s...`);
        setTimeout(() => { if (currentUsername) connect(currentUsername); }, 10000);
    });

    tiktokConnection.on('error', (err) => {
        console.error('[TikTok] Error:', err.message);
    });
}

function disconnect() {
    if (tiktokConnection) tiktokConnection.disconnect();
    tiktokConnection = null;
    currentUsername = null;
}

module.exports = { connect, disconnect, giftQueue };