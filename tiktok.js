const { WebcastPushConnection } = require('tiktok-live-connector');

const giftQueue = [];
let connection = null;
let currentUsername = null;

function connect(username) {
    if (connection) connection.disconnect();

    currentUsername = username;
    connection = new WebcastPushConnection(username, {
        processInitialData: false,
        enableExtendedGiftInfo: true,
    });

    connection.connect()
        .then(() => console.log(`[TikTok] Connected: @${username}`))
        .catch(err => console.error(`[TikTok] Connect failed:`, err.message));

    connection.on('gift', (data) => {
        if (data.giftType === 1 && !data.repeatEnd) return;
        giftQueue.push({
            giftId: String(data.giftId),
            giftName: data.giftName || 'unknown',
            count: data.repeatCount || 1,
            sender: data.nickname || 'unknown',
        });
        console.log(`[GIFT] ${data.giftName} x${data.repeatCount} from ${data.nickname}`);
    });

    connection.on('disconnected', () => {
        console.warn(`[TikTok] Disconnected — reconnect in 10s...`);
        setTimeout(() => { if (currentUsername) connect(currentUsername); }, 10000);
    });

    connection.on('error', (err) => {
        console.error('[TikTok] Error:', err.message);
    });
}

function disconnect() {
    if (connection) connection.disconnect();
    connection = null;
    currentUsername = null;
}

module.exports = { connect, disconnect, giftQueue };