const express = require('express');
const tiktok  = require('./tiktok');

const app    = express();
const API_KEY = process.env.API_KEY || 'tiktok-reactive-gift-queue-129DJJ';

app.use(express.json());

function auth(req, res, next) {
    if (req.headers['x-api-key'] !== API_KEY) return res.status(401).json({ error: 'Unauthorized' });
    next();
}

app.get('/gifts/poll', auth, (req, res) => {
    res.json(tiktok.giftQueue.splice(0, 50));
});

app.post('/session/start', auth, (req, res) => {
    const { username } = req.body;
    if (!username) return res.status(400).json({ error: 'username required' });
    tiktok.connect(username);
    res.json({ ok: true });
});

app.post('/session/stop', auth, (req, res) => {
    tiktok.disconnect();
    tiktok.giftQueue.length = 0;
    res.json({ ok: true });
});

app.get('/status', auth, (req, res) => {
    res.json({ queueLength: tiktok.giftQueue.length, uptime: process.uptime() });
});

app.listen(process.env.PORT || 3000, () => console.log(`[Server] Running`));