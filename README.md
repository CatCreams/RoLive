Berikut isi `README.md` yang bisa kamu salin lalu edit. Ganti `YOUR_CHANNEL` dan `YOUR_INVITE` dengan tautan YouTube dan Discord milikmu.

````markdown name=README.md
<div align="center">

# TikTok Reactive Live Bridge

**Jembatan event TikTok LIVE ke Roblox** — pantau stream dan kirim event gift, like, follow, serta chat ke Roblox Messaging Service.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![HTML](https://img.shields.io/badge/HTML-dashboard-E34F26?logo=html5&logoColor=white)](https://developer.mozilla.org/en-US/docs/Web/HTML)
[![Deploy on Railway](https://img.shields.io/badge/Deploy-Railway-0B0D0E?logo=railway&logoColor=white)](https://railway.app/)
[![TikTokLive](https://img.shields.io/badge/TikTokLive-6.4.3-000000?logo=tiktok&logoColor=white)](https://pypi.org/project/TikTokLive/)

[![YouTube](https://img.shields.io/badge/YouTube-Subscribe-FF0000?logo=youtube&logoColor=white)](https://www.youtube.com/@YOUR_CHANNEL)
[![Discord](https://img.shields.io/badge/Discord-Join%20server-5865F2?logo=discord&logoColor=white)](https://discord.gg/YOUR_INVITE)

</div>

## Tentang proyek

RoLive adalah backend FastAPI yang terhubung ke TikTok LIVE. Backend menerima event live melalui `TikTokLive`, menyimpan event sementara dalam antrean, lalu meneruskannya ke Roblox Open Cloud Messaging Service dengan topic `TikTokEvents`. Dashboard web menampilkan sesi, statistik, dan feed event.

**Event yang didukung:**

- Gift
- Like
- Follow, jika didukung oleh versi library/event TikTokLive yang terpasang
- Chat atau komentar
- Jumlah penonton, jika event tersedia

> Repository ini menyediakan sisi bridge/backend dan dashboard. Script Roblox yang berlangganan topic `TikTokEvents` perlu dibuat dan dipasang secara terpisah di game Roblox.

## Teknologi

- **Backend:** Python, FastAPI, Uvicorn
- **Koneksi live:** TikTokLive
- **Dashboard:** HTML, CSS, JavaScript
- **Integrasi game:** Roblox Open Cloud Messaging Service
- **Hosting:** Railway

## Persiapan

Sebelum mulai, siapkan:

1. Akun GitHub dan Railway.
2. Game Roblox dan **Universe ID**-nya.
3. Roblox Open Cloud API key dengan izin untuk mengirim pesan melalui Messaging Service pada universe tersebut.
4. Username akun TikTok yang sedang LIVE ketika sesi akan dimulai.

Simpan API key sebagai secret/environment variable di Railway atau di file `.env` lokal. **Jangan commit API key atau file `.env` ke repository.**

## Deploy ke Railway

1. Push atau fork repository ini ke akun GitHub-mu.
2. Di Railway, buat project baru dan pilih **Deploy from GitHub repo**, lalu pilih repository RoLive.
3. Pastikan root directory mengarah ke root repository. Dependensi ada di `requirements.txt`, sedangkan `Procfile` menjalankan aplikasi dengan `python main.py`.
4. Tambahkan environment variables berikut di bagian **Variables** pada Railway:

   | Variable | Wajib | Keterangan |
   | --- | --- | --- |
   | `API_KEY` | Ya | Secret acak yang digunakan untuk melindungi endpoint kontrol sesi. Buat sendiri dan jangan gunakan contoh publik. |
   | `UNIVERSE_ID` | Ya | ID universe Roblox. Digunakan untuk informasi game dan pengiriman pesan. |
   | `ROBLOX_API_KEY` | Ya untuk mengirim event ke Roblox | Roblox Open Cloud API key dengan izin publish Messaging Service untuk universe tujuan. |
   | `RAILWAY_URL` | Disarankan | URL publik service, misalnya `https://nama-service.up.railway.app`, tanpa slash di akhir. Digunakan untuk membuat URL avatar. |

   Kamu bisa membuat secret acak untuk `API_KEY` menggunakan Python:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

5. Buat **Public Domain** untuk service Railway jika belum tersedia.
6. Isi `RAILWAY_URL` dengan domain publik tersebut tanpa slash di akhir. Redeploy service jika perlu.
7. Buka domain Railway untuk melihat dashboard. Dashboard tersedia di `/`.
8. Periksa deployment logs jika service gagal dijalankan.

> Jika `ROBLOX_API_KEY` atau `UNIVERSE_ID` tidak diatur, server masih dapat berjalan, tetapi event tidak akan dikirim ke Roblox.

## Jalankan secara lokal

Pastikan Python 3.10 atau lebih baru telah terpasang.

Clone repository dan buat virtual environment:

```bash
git clone https://github.com/CatCreams/RoLive.git
cd RoLive
python -m venv .venv
```

Aktifkan virtual environment:

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

Pasang dependensi:

```bash
python -m pip install -r requirements.txt
```

Buat file `.env` di root proyek:

```dotenv
API_KEY=ganti_dengan_secret_acak
UNIVERSE_ID=id_universe_roblox
ROBLOX_API_KEY=roblox_open_cloud_api_key
RAILWAY_URL=http://localhost:8080
```

Jalankan server:

```bash
python main.py
```

Buka [http://localhost:8080](http://localhost:8080) untuk melihat dashboard. Pastikan file `.env` tidak di-commit.

## Memulai sesi TikTok LIVE

Endpoint kontrol memerlukan header `x-api-key` yang nilainya sama dengan `API_KEY`.

Contoh memulai sesi:

```bash
curl -X POST http://localhost:8080/session/start \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: GANTI_DENGAN_API_KEY' \
  -d '{"username":"username_tiktok"}'
```

Username harus sedang melakukan LIVE agar koneksi dapat berhasil.

Endpoint kontrol sesi lainnya:

```text
POST /session/pause
POST /session/resume
POST /session/stop
```

Kirim username sebagai JSON, misalnya:

```json
{
  "username": "username_tiktok"
}
```

Gunakan header `x-api-key` yang sama untuk endpoint kontrol tersebut. Untuk menghentikan semua sesi, panggil `/session/stop` tanpa username atau dengan body kosong.

## Endpoint utama

| Method | Path | Keterangan | Perlu API key |
| --- | --- | --- | --- |
| `GET` | `/` | Dashboard HTML | Tidak |
| `GET` | `/api/dashboard` | Status bridge, daftar sesi, dan informasi game Roblox | Tidak |
| `GET` | `/api/sessions` | Daftar sesi | Tidak |
| `GET` | `/api/events` | Melihat event terbaru tanpa menghapus antrean | Tidak |
| `GET` | `/events/poll` | Mengambil dan menghapus event dari antrean | Ya |
| `POST` | `/session/start` | Memulai koneksi TikTok LIVE | Ya |
| `POST` | `/session/pause` | Mengabaikan event untuk sementara | Ya |
| `POST` | `/session/resume` | Melanjutkan pemrosesan event | Ya |
| `POST` | `/session/stop` | Menghentikan sesi | Ya |
| `GET` | `/api/avatar/{username}` | Mengambil avatar streamer | Tidak |
| `POST` | `/api/roblox/lookup` | Mencari username Roblox | Tidak |

## Alur event Roblox

Ketika event diterima, bridge mengirim JSON ke Roblox Open Cloud Messaging Service dengan topic **`TikTokEvents`**. Payload memiliki field umum seperti `eventId`, `type`, `username`, dan `timestamp`, ditambah data sesuai jenis event, seperti nama gift atau isi chat.

Game Roblox perlu memiliki kode server-side yang berlangganan topic tersebut dan memproses pesan. Messaging Service ditujukan untuk komunikasi server-ke-server. **Jangan menaruh `ROBLOX_API_KEY` di client Roblox atau membagikannya kepada pemain.**

## Keamanan dan catatan

- Gunakan secret kuat untuk `API_KEY` dan batasi akses ke domain service sesuai kebutuhan.
- Jangan publikasikan `ROBLOX_API_KEY`, `API_KEY`, atau isi file `.env`.
- Beberapa endpoint informasi bersifat publik dalam implementasi saat ini. Hindari mengirim data sensitif melalui endpoint tersebut.
- Koneksi TikTok LIVE bergantung pada layanan dan library pihak ketiga. Perubahan TikTok dapat memengaruhi koneksi atau event yang tersedia.
- Antrean event disimpan di memori proses. Event dapat hilang ketika service restart atau antrean penuh.

## Lisensi

Tambahkan informasi lisensi proyek di bagian ini jika repository memiliki file lisensi.

---

Dibuat untuk menghubungkan event TikTok LIVE dengan pengalaman Roblox secara real-time. Pastikan penggunaan mematuhi ketentuan TikTok, Roblox, Railway, dan hak pengguna yang terkait.
````
