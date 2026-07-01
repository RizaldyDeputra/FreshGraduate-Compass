# JobStreet to Notion

Automatically fetches JobStreet email alerts from Gmail, filters them with Gemini AI,
and saves matching listings to a Notion database.

Gmail IMAP → Gemini 2.5 Flash → Notion

---

## Prasyarat

- Akun Gmail (dengan IMAP aktif)
- [Google AI Studio](https://aistudio.google.com) API key
- [Notion](https://notion.so) workspace + integration
- [GitHub](https://github.com) account (untuk scheduled runs)
- Python 3.11+

---

## Setup

### 1. Aktifkan IMAP di Gmail

Gmail → Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP → Save.

### 2. Buat Gmail App Password

Butuh 2-Step Verification aktif dulu.

1. Buka [myaccount.google.com/security](https://myaccount.google.com/security)
2. Cari "App passwords" → App: Mail, Device: Other → ketik "JobFilter" → Generate
3. Salin password 16 karakter, hapus spasi → `xxxxxxxxxxxxxxxx`

### 3. Dapatkan Gemini API Key

Buka [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) → Create API Key → salin.

### 4. Setup Notion

**Buat integration:**
[notion.so/my-integrations](https://www.notion.so/my-integrations) → New integration → nama: `JobFilter Bot` → Submit → salin token (`secret_...`).

**Buat database** dengan properti:

| Properti            | Tipe    |
|---------------------|---------|
| `Name`              | Title   |
| `Company`           | Text    |
| `Location`          | Text    |
| `Link`              | URL     |
| `Score`             | Number  |
| `Label`             | Select  |
| `Experience Required` | Text  |
| `Reason`            | Text    |
| `Highlight`         | Text    |
| `Status`            | Select  |
| `Date Found`        | Date    |

Label options: `Priority`, `Good`, `Maybe`, `Skip`

Status options: `New`, `Applied`, `Waiting`, `Accepted`, `Rejected`

**Connect integration ke database:** buka database → `...` → Connect to → pilih `JobFilter Bot`.

**Salin Database ID** dari URL: `notion.so/{workspace}/{DATABASE_ID}?v=...`

### 5. Setup GitHub

Upload ke repo, lalu tambahkan secrets di Settings → Secrets and variables → Actions:

| Secret Name          | Nilai                          |
|----------------------|--------------------------------|
| `GMAIL_USER`         | emailkamu@gmail.com            |
| `GMAIL_APP_PASSWORD` | App Password (tanpa spasi)     |
| `GEMINI_API_KEY`     | API key dari Google AI Studio  |
| `NOTION_TOKEN`       | Integration token              |
| `NOTION_DATABASE_ID` | ID database (32 karakter)      |
| `CANDIDATE_PROFILE`  | Profil kandidat (lihat bawah)  |

### 6. Setup JobStreet Email Alert

Login [jobstreet.co.id](https://www.jobstreet.co.id) → set filter → Save search / Get email alerts → frekuensi: Daily.

### 7. Test

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env
python job_filter.py
```

Atau via GitHub Actions: tab Actions → pilih workflow → Run workflow.

---

## Jadwal

Berjalan setiap hari 09.00 WIB otomatis via GitHub Actions.

Edit cron di `.github/workflows/daily_job_filter.yml`:
```yaml
cron: '0 2 * * *'   # 09.00 WIB (UTC+7)
```

Format: `menit jam * * *` (UTC)

---

## Kustomisasi Profil

Set `CANDIDATE_PROFILE` di `.env` (lokal) atau GitHub Secrets. Tulis profil kamu sebagai bullet points, contoh:

```
- Fresh graduate S1 Teknik Informatika, Private University
- Skills: Python, SQL, Power BI
- Target role: Data Analyst
- Lokasi: Jakarta, Surabaya, Remote
```

Semakin spesifik, semakin akurat filternya.

---

## Troubleshooting

**Email tidak terdeteksi** — cek IMAP aktif, cek apakah alert masuk Spam/Promotions.

**Login failed** — App Password salah atau 2FA belum aktif.

**Gemini error** — cek API key. Free tier limit: 15 req/menit.

**Notion "property does not exist"** — nama properti harus persis sama (case-sensitive), cek tabel di atas.
