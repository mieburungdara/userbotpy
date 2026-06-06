# userbotpy

Telegram UserBot sederhana menggunakan Pyrogram (Python) dengan dukungan multi-akun.

## Fitur

**Bot Commands:**
- `/start` - Mulai bot
- `/ping` - Cek latency bot
- `/echo` - Mengulangi teks
- `/info` - Informasi userbot
- `/alive` - Cek apakah bot aktif
- `/help` - Menampilkan daftar perintah

**Multi-Account Commands:**
- `/login` - Login akun baru via kontak
- `/cancel` - Batalkan proses login
- `/accounts` - Lihat akun terdaftar

**Backup Media Commands:**
- `/backup` - Backup media dari channel/group ke channel backup

## Persiapan

1. Dapatkan **API ID** dan **API HASH** dari [my.telegram.org](https://my.telegram.org/apps)
2. Buat Bot Token dari **@BotFather** di Telegram

## Instalasi

```bash
pip install -r requirements.txt
```

## Konfigurasi

Salin file `.env.example` menjadi `.env` dan isi konfigurasinya:

```bash
cp .env.example .env
```

Edit `.env`:

```env
API_ID=1234567
API_HASH=0123456789abcdef0123456789abcdef
BOT_TOKEN=1234567890:ABCDEF-GHIJKLmnopqrstuVWXYZ
PREFIX=!  # Prefix untuk perintah

# Optional: PostgreSQL/Supabase Database URL untuk persistensi session
# DATABASE_URL=postgresql://postgres:password@localhost:5432/userbot_db
```

### Konfigurasi Database (Opsional)

Untuk menyimpan session di database PostgreSQL/Supabase:

1. **Setup Supabase:**
   - Buat project di [supabase.com](https://supabase.com)
   - Dapatkan connection string dari Settings > Database
   - Format: `postgresql://postgres:password@db.xxx.supabase.co:5432/postgres`

2. **Setup PostgreSQL lokal:**
   ```bash
   # Install PostgreSQL
   sudo apt install postgresql postgresql-contrib
   
   # Create database
   createdb userbot_db
   ```

3. **Tabel akan dibuat otomatis:**
   - Tabel `userbot_sessions` dengan kolom: `user_id`, `phone`, `session_string`

4. **Keuntungan:**
   - Session tidak hilang saat restart
   - Bisa diakses dari multiple instance

## Cara Login Multi-Account

1. **Mulai proses login:**
   ```
   /login
   ```
   atau klik tombol "Login via Kontak" di `/start`

2. **Bagikan kontak Anda:**
   - Klik ikon paperclip di Telegram
   - Pilih "Contact"
   - Pilih kontak yang ingin dijadikan userbot

3. **Masukkan kode:**
   - Telegram akan mengirim kode ke akun Anda
   - Gunakan tombol angka inline untuk input kode
   - Klik "✅ Kirim" untuk verifikasi

4. **Jika akun menggunakan 2FA:**
   - Kirim password sebagai pesan teks langsung ke bot
   - Contoh: ketik `password123` dan kirim

5. **Batalkan proses:**
   ```
   /cancel
   ```

6. **Lihat akun yang tersimpan:**
   ```
   /accounts
   ```

## Cara Backup Media

1. **Login akun userbot** terlebih dahulu menggunakan `/login`

2. **Mulai proses backup:**
   ```
   /backup
   ```
   - Jika ada multiple akun, pilih userbot yang akan digunakan

3. **Input channel sumber:**
   - Kirim username atau link channel/group sumber
   - Contoh: `@mychannel` atau `https://t.me/mychannel`

4. **Input channel tujuan:**
   - Kirim username atau link channel backup
   - Userbot perlu menjadi admin di channel target

5. **Konfirmasi dan proses:**
   - Klik "Mulai Backup" untuk memulai
   - Sistem akan otomatis mengirim semua media ke channel backup

6. **Hasil backup:**
   - Semua pesan berisi media (photo, video, document, album) akan dikirim
   - Progress ditampilkan di chat
   - Pesan selesai menunjukkan total terkirim

## Menjalankan

```bash
python userbot.py
```

## Perintah yang Tersedia

| Perintah | Deskripsi |
|----------|-----------|
| `/start` | Mulai bot |
| `/ping` | Cek latency |
| `/echo [teks]` | Mengulangi teks |
| `/info` | Info userbot |
| `/alive` | Cek status bot |
| `/login` | Login akun baru |
| `/cancel` | Batalkan proses login |
| `/accounts` | Lihat akun terdaftar |
| `/backup` | Backup media ke channel lain |

## Lisensi

MIT License