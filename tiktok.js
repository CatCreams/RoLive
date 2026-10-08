const { TikTokLiveConnection, WebcastEvent, ControlEvent } = require('tiktok-live-connector');

const giftQueue = [];
let connection = null;
let currentUsername = null;

function connect(username) {
    if (connection) connection.disconnect();

    currentUsername = username;
    connection = new TikTokLiveConnection(username, {
        signApiKey: process.env.EULER_API_KEY || '',
        processInitialData: false,
        enableExtendedGiftInfo: true,
    });

    connection.connect()
        .then(() => console.log(`[TikTok] Connected: @${username}`))
        .catch(err => console.error(`[TikTok] Connect failed:`, err.message));

    connection.on(WebcastEvent.GIFT, (data) => {
        const giftType = data.giftDetails?.giftType;
        console.log(`[RAW] id:${data.giftId} name:${data.giftDetails?.giftName} type:${giftType} repeatEnd:${data.repeatEnd} sender:${data.user?.nickname}`);
        if (giftType === 1 && !data.repeatEnd) return;
        giftQueue.push({
            giftId: String(data.giftId),
            giftName: data.giftDetails?.giftName || 'unknown',
            count: data.repeatCount || 1,
            sender: data.user?.nickname || 'unknown',
        });
    });

    connection.on(ControlEvent.DISCONNECTED, () => {
        console.warn(`[TikTok] Disconnected — reconnect in 10s...`);
        setTimeout(() => { if (currentUsername) connect(currentUsername); }, 10000);
    });

    connection.on(ControlEvent.ERROR, ({ info, exception }) => {
        console.error('[TikTok] Error:', info, exception?.message);
    });
}

function disconnect() {
    if (connection) connection.disconnect();
    connection = null;
    currentUsername = null;
}

module.exports = { connect, disconnect, giftQueue };