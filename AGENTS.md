# AGENTS.md - userbotpy

## Overview
Single-file Telegram UserBot using Pyrogram with multi-account support and optional PostgreSQL/Supabase persistence.

## Running
```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with API_ID, API_HASH, BOT_TOKEN
python userbot.py
```

## Architecture
- `userbot.py` - Main entry point, bot commands, backup handlers
- `login_helper.py` - Session management, database operations, login/2FA flows

## Key Behavior Notes
- Sessions persist in `.session` files by default; set `DATABASE_URL` for PostgreSQL persistence
- Database tables (`userbot_sessions`, `backup_progress`, `backup_configs`) created automatically on startup
- Userbots lazy-load from DB on demand: `ubot_{user_id}_{phone}` naming convention
- Phone numbers with `62` prefix auto-converted to `+62` format
- Automatic 4-5s random delay between forwarded messages to prevent Telegram throttling

## No Tests/Lint
This project has no test framework or linting configured.