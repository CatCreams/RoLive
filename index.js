import express from 'express';
import { connect, disconnect, poll, status } from './tiktok.js';

const app     = express();
const API_KEY = process.env.API_KEY || 'tiktok-reactive-gift-queue-129DJJ';
const PORT    = process.env.PORT    || 8080;

app.use(express.json());

function auth(req, res, next) {
    if (req.headers['x-api-key'] !== API_KEY) {
        return res.status(401).json({ error: 'Unauthorized' });
    }
    next();
}

app.get('/', (req, res) => {
    res.send('Tiktok Live Bridge is running');
});

app.post('/session/start', auth, (req, res) => {
    const { username } = req.body;
    if (!username) return res.status(400).json({ error: 'username required' });
    connect(username);
    res.json({ ok: true });
});

app.post('/session/stop', auth, (req, res) => {
    disconnect();
    res.json({ ok: true });
});

app.get('/events/poll', auth, (req, res) => {
    const limit = Math.min(parseInt(req.query.limit) || 100, 200);
    res.json(poll(limit));
});

app.get('/status', auth, (req, res) => {
    res.json({ ...status(), uptime: process.uptime() });
});

app.listen(PORT, () => console.log(`[Server] Running on :${PORT}`));