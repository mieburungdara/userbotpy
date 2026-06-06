import os
import time
import logging
import asyncio
from typing import Optional
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from login_helper import (
    start_login_process,
    verify_login_code,
    verify_2fa_password,
    get_user_sessions,
    pending_logins,
    load_session_from_db_sync,
    init_database,
    save_session_to_db,
    is_message_backed_up,
    mark_message_backed_up,
    save_backup_config,
    get_backup_configs,
    clear_backup_progress,
)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PREFIX = os.getenv("PREFIX", "!")

# Initialize database on startup
db_initialized = init_database()

# Validate required credentials
if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise ValueError("API_ID, API_HASH, and BOT_TOKEN must be set in environment variables")


# Initialize main bot client
app = Client(
    "main_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# Store user input state for numeric keyboard
user_code_input = {}

# Store active userbot clients: {session_name: Client}
active_userbots = {}

# Store backup process state: {user_id: {"source": chat, "target": chat, "state": str}}
backup_sessions = {}


def get_numeric_keyboard():
    """Create inline keyboard with numbers 0-9"""
    keyboard = []
    for i in range(3):
        row = []
        for j in range(3):
            num = i * 3 + j + 1
            row.append(InlineKeyboardButton(str(num), callback_data=f"num_{num}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("0", callback_data="num_0")])
    keyboard.append([
        InlineKeyboardButton("⬅️ Hapus", callback_data="backspace"),
        InlineKeyboardButton("✅ Kirim", callback_data="submit_code")
    ])
    return InlineKeyboardMarkup(keyboard)


def get_cancel_keyboard():
    """Create inline keyboard with cancel button"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Batal", callback_data="cancel_login")]
    ])


def get_userbot_list_keyboard(user_id: int, sessions: list) -> InlineKeyboardMarkup:
    """Create inline keyboard with userbot list"""
    keyboard = []
    for phone in sessions:
        keyboard.append([InlineKeyboardButton(f"🤖 {phone}", callback_data=f"ubot_{phone}")])
    
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh_ubots")])
    return InlineKeyboardMarkup(keyboard)


@app.on_message(filters.private & filters.command("start", PREFIX))
async def start_command(client: Client, message: Message):
    """Handle /start command"""
    await message.reply_text(
        f"👋 Hai {message.from_user.first_name}!\n\n"
        "Saya adalah UserBot Telegram yang siap membantu.\n\n"
        "**Perintah Utama:**\n"
        f"{PREFIX}ping - Cek latency\n"
        f"{PREFIX}echo [teks] - Mengulangi teks\n"
        f"{PREFIX}alive - Cek status bot\n\n"
        "**Multi-Account UserBot:**\n"
        f"{PREFIX}login - Login akun baru\n"
        f"{PREFIX}accounts - Lihat akun terdaftar\n"
        f"{PREFIX}cancel - Batalkan proses login",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 Login via Kontak", callback_data="request_contact")]
        ])
    )


@app.on_message(filters.private & filters.command("help", PREFIX))
async def help_command(client: Client, message: Message):
    """Handle /help command"""
    help_text = f"""
🤖 **Daftar Perintah UserBot**

**Bot Commands:**
{PREFIX}start - Mulai bot
{PREFIX}ping - Cek latency bot
{PREFIX}echo [teks] - Mengulangi teks
{PREFIX}info - Informasi userbot
{PREFIX}alive - Cek apakah bot aktif

**Multi-Account Commands:**
{PREFIX}login - Mulai login akun baru
{PREFIX}accounts - Lihat akun terdaftar
{PREFIX}cancel - Batalkan proses login

**Backup Media Commands:**
{PREFIX}backup - Backup media dari channel/group ke channel backup

**Cara Login:**
1. Ketik `{PREFIX}login` atau klik tombol "Login via Kontak"
2. Bagikan kontak Anda ke bot
3. Telegram akan mengirim kode ke akun Anda
4. Gunakan tombol angka untuk input kode
5. Jika butuh 2FA, kirim password sebagai pesan teks langsung

**Cara Backup Media:**
1. Login akun userbot dahulu dengan `{PREFIX}login`
2. Ketik `{PREFIX}backup` untuk memulai
3. Kirim username/link channel sumber
4. Kirim username/link channel tujuan (backup)
5. Konfirmasi dan tunggu proses selesai
"""
    await message.reply_text(help_text, disable_web_page_preview=True)


@app.on_message(filters.private & filters.command("ping", PREFIX))
async def ping_command(client: Client, message: Message):
    """Handle /ping command"""
    start_time = time.time()
    reply = await message.reply_text("🏓 Ping...")
    end_time = time.time()
    latency = (end_time - start_time) * 1000
    await reply.edit_text(f"🏓 Pong!\nLatency: `{latency:.2f}ms`")


@app.on_message(filters.private & filters.command("echo", PREFIX))
async def echo_command(client: Client, message: Message):
    """Handle /echo command"""
    if len(message.text.split()) < 2:
        return await message.reply_text(f"❌ Gunakan: `{PREFIX}echo [teks]`")
    
    text = message.text.split(None, 1)[1]
    await message.reply_text(text)


@app.on_message(filters.private & filters.command("info", PREFIX))
async def info_command(client: Client, message: Message):
    """Handle /info command"""
    me = await client.get_me()
    await message.reply_text(
        f"**Informasi UserBot**\n\n"
        f"**Nama:** {me.first_name}\n"
        f"**Username:** @{me.username if me.username else 'Tidak ada'}\n"
        f"**ID:** `{me.id}`\n"
    )


@app.on_message(filters.private & filters.command("alive", PREFIX))
async def alive_command(client: Client, message: Message):
    """Handle /alive command"""
    await message.reply_text("✅ Bot sedang aktif dan berfungsi!")


@app.on_message(filters.command("ping", PREFIX) & filters.group)
async def ping_group(client: Client, message: Message):
    """Handle /ping command in groups"""
    start_time = time.time()
    reply = await message.reply_text("🏓 Ping...")
    end_time = time.time()
    latency = (end_time - start_time) * 1000
    await reply.edit_text(f"🏓 Pong!\nLatency: `{latency:.2f}ms`")


@app.on_message(filters.private & filters.command("cancel", PREFIX))
async def cancel_command(client: Client, message: Message):
    """Handle /cancel command - Cancel pending login"""
    user_id = message.from_user.id
    cancelled = False
    
    if user_id in pending_logins:
        login_data = pending_logins[user_id]
        if login_data.get("client"):
            try:
                await login_data["client"].disconnect()
            except Exception:
                pass
        del pending_logins[user_id]
        cancelled = True
    
    if user_id in user_code_input:
        del user_code_input[user_id]
        cancelled = True
    
    if cancelled:
        await message.reply_text("✅ Proses login telah dibatalkan.")
    else:
        await message.reply_text("❌ Tidak ada proses login yang sedang berjalan.")


# Multi-Account Commands
@app.on_message(filters.private & filters.command("login", PREFIX))
async def login_command(client: Client, message: Message):
    """Handle /login command - Request contact sharing"""
    user_id = message.from_user.id
    
    await message.reply_text(
        "📱 Untuk login, bot memerlukan nomor telepon Anda.\n\n"
        "Klik tombol di bawah ini untuk berbagi kontak:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 Berbagi Nomor Telepon", callback_data="request_contact")]
        ])
    )


@app.on_message(filters.private & filters.command("backup", PREFIX))
async def backup_command(client: Client, message: Message):
    """Handle /backup command - Start media backup process"""
    user_id = message.from_user.id
    
    # Check if user has any logged in accounts
    sessions = get_user_sessions(user_id)
    if not sessions:
        return await message.reply_text("❌ Anda belum login akun userbot manapun. Gunakan `/login` terlebih dahulu.")
    
    # Show saved backup configs if any
    saved_configs = get_backup_configs(user_id)
    
    if saved_configs:
        keyboard = []
        for cfg in saved_configs[:5]:  # Max 5 configs
            source_short = cfg['source'][:20] + "..." if len(cfg['source']) > 20 else cfg['source']
            target_short = cfg['target'][:20] + "..." if len(cfg['target']) > 20 else cfg['target']
            keyboard.append([InlineKeyboardButton(
                f"🔁 {cfg['source_title'] or source_short} → {cfg['target_title'] or target_short}",
                callback_data=f"quick_backup_{cfg['source']}|{cfg['target']}"
            )])
        keyboard.append([InlineKeyboardButton("➕ Backup Baru", callback_data="new_backup")])
        keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="cancel_backup")])
        
        return await message.reply_text(
            "**📥 Backup Media UserBot**\n\n"
            "Pilih konfigurasi backup atau buat yang baru:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # If multiple accounts, ask user to select one
    if len(sessions) > 1:
        keyboard = []
        for phone in sessions:
            keyboard.append([InlineKeyboardButton(f"🤖 {phone}", callback_data=f"backup_ubot_{phone}")])
        keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="cancel_backup")])
        
        return await message.reply_text(
            "**📥 Backup Media UserBot**\n\n"
            "Pilih akun userbot yang akan digunakan:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # Use the only available account
    phone = sessions[0]
    session_name = f"ubot_{user_id}_{phone.replace('+', '').replace(' ', '')}"
    userbot_client = active_userbots.get(session_name)
    
    # Try to load from database if not active
    if not userbot_client and db_initialized:
        session_string = load_session_from_db_sync(user_id, phone.replace("+", ""))
        if session_string:
            try:
                userbot_client = Client(
                    session_name,
                    api_id=API_ID,
                    api_hash=API_HASH,
                    session_string=session_string,
                    in_memory=True
                )
                await userbot_client.connect()
                await userbot_client.get_me()
                active_userbots[session_name] = userbot_client
            except Exception as e:
                logger.error(f"Failed to load session from DB in backup: {e}")
                userbot_client = None
    
    if not userbot_client:
        return await message.reply_text(
            "⚠️ Tidak ada userbot yang aktif. Userbot perlu di-login ulang karena restart bot.\n"
            "Gunakan `/login` untuk login kembali."
        )
    
    backup_sessions[user_id] = {
        "client": userbot_client,
        "source": None,
        "target": None,
        "state": "waiting_source"
    }
    
    await message.reply_text(
        f"**📥 Backup Media UserBot**\n\n"
        f"Userbot: 🤖 {phone}\n\n"
        f"Silakan kirim **username atau link** channel/group sumber (misal: @channelname atau https://t.me/channelname):\n\n"
        f"Contoh: `@mychannel` atau `https://t.me/mychannel`",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Batal", callback_data="cancel_backup")]
        ])
    )


@app.on_message(filters.private & filters.command("backupconfigs", PREFIX))
async def backupconfigs_command(client: Client, message: Message):
    """Handle /backupconfigs command - List saved backup configurations"""
    user_id = message.from_user.id
    configs = get_backup_configs(user_id)
    
    if not configs:
        return await message.reply_text(
            "❌ Tidak ada konfigurasi backup yang tersimpan.\n\n"
            "Gunakan `/backup` untuk membuat konfigurasi baru."
        )
    
    config_list = "**🔖 Konfigurasi Backup yang Tersimpan:**\n\n"
    for i, cfg in enumerate(configs, 1):
        config_list += f"{i}. **Source:** `{cfg['source_title'] or cfg['source']}`\n"
        config_list += f"   **Target:** `{cfg['target_title'] or cfg['target']}`\n\n"
    
    config_list += "\nGunakan `/backup` untuk memulai backup baru."
    await message.reply_text(config_list)


@app.on_message(filters.private & filters.command("accounts", PREFIX))
async def accounts_command(client: Client, message: Message):
    """Handle /accounts command - List registered accounts"""
    user_id = message.from_user.id
    sessions = get_user_sessions(user_id)
    accounts_list = f"📱 **Akun UserBot yang tersimpan:**\n\n" + "\n".join(f"• `{a}`" for a in sessions) if sessions else "❌ Tidak ada akun yang tersimpan."
    
    if sessions:
        accounts_list += "\n\n📁 Pilih akun untuk mengirim perintah:"
        await message.reply_text(accounts_list, reply_markup=get_userbot_list_keyboard(user_id, sessions))
    else:
        accounts_list += "\n\nGunakan `/login` untuk menambah akun."
        await message.reply_text(accounts_list)


# Handle contact sharing
@app.on_message(filters.private & filters.contact)
async def contact_handler(client: Client, message: Message):
    """Handle contact sharing for phone number"""
    user_id = message.from_user.id
    phone = message.contact.phone_number
    
    # Ensure phone has + prefix
    if not phone.startswith("+"):
        phone = "+" + phone
    
    logger.info(f"Received contact from user {user_id}: {phone}")
    
    success, result_msg = await start_login_process(user_id, phone, API_ID, API_HASH)
    
    if success:
        # Initialize code input for this user
        user_code_input[user_id] = {"code": ""}
        await message.reply_text(
            result_msg + "\n\nMasukkan kode yang Anda terima dari Telegram:",
            reply_markup=get_numeric_keyboard()
        )
    else:
        await message.reply_text(result_msg)


# Handle text messages for 2FA password and backup input
@app.on_message(filters.private & filters.text & ~filters.regex(f"^{PREFIX}"))
async def text_handler(client: Client, message: Message):
    """Handle text messages - used for 2FA password input and backup configuration"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Check if user is in 2FA state
    if user_id in pending_logins and pending_logins[user_id].get("needs_2fa"):
        await message.reply_text("⏳ Memverifikasi password 2FA...")
        
        phone = pending_logins[user_id]["phone"].replace("+", "").replace(" ", "")
        session_name = f"ubot_{user_id}_{phone}"
        
        success, result_msg, user_client, _ = await verify_2fa_password(user_id, text)
        await message.reply_text(result_msg)
        
        if success and user_client:
            active_userbots[session_name] = user_client
        
        return
    
    # Check if user is in backup session
    if user_id in backup_sessions:
        backup_data = backup_sessions[user_id]
        
        if backup_data["state"] == "waiting_source":
            await _process_backup_source(client, message, text)
        elif backup_data["state"] == "waiting_target":
            await _process_backup_target(client, message, text)
        return
    
    # If there's pending login but not 2FA state, ignore or give hint
    if user_id in pending_logins:
        await message.reply_text("⏳ Silakan masukkan kode menggunakan tombol di pesan sebelumnya.")


async def _process_backup_source(client: Client, message: Message, text: str):
    """Process source channel input for backup"""
    user_id = message.from_user.id
    backup_data = backup_sessions[user_id]
    userbot_client = backup_data.get("client")
    
    # Lazy load session from database if not active - use user's saved phone
    if not userbot_client and db_initialized:
        sessions = get_user_sessions(user_id)
        if sessions:
            # Use first available session phone for lazy loading
            phone = sessions[0].replace("+", "")
            session_string = load_session_from_db_sync(user_id, phone)
            if session_string:
                try:
                    session_name = f"ubot_{user_id}_{phone.replace('+', '').replace(' ', '')}"
                    userbot_client = Client(
                        session_name,
                        api_id=API_ID,
                        api_hash=API_HASH,
                        session_string=session_string,
                        in_memory=True
                    )
                    await userbot_client.connect()
                    await userbot_client.get_me()
                    backup_sessions[user_id]["client"] = userbot_client
                    active_userbots[session_name] = userbot_client
                except Exception as e:
                    logger.error(f"Failed to load session from DB for backup: {e}")
                    return await message.reply_text(f"❌ Gagal memuat sesi userbot: {str(e)}")
    
    if not userbot_client:
        return await message.reply_text("❌ Userbot tidak tersedia. Login ulang diperlukan.")
    
    # Parse chat from text (username or link)
    chat = text.replace("https://t.me/", "").replace("@", "").strip()
    
    try:
        # Try to get chat info
        chat_info = await userbot_client.get_chat(chat)
        backup_sessions[user_id]["source"] = chat_info.username or chat_info.id
        backup_sessions[user_id]["state"] = "waiting_target"
        
        await message.reply_text(
            f"✅ **Source:** `{chat_info.title or chat_info.first_name}`\n\n"
            f"Sekarang kirim **username atau link** channel/group tujuan (backup):\n\n"
            f"Contoh: `@backupchannel` atau `https://t.me/backupchannel`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ganti Source", callback_data="change_source")],
                [InlineKeyboardButton("❌ Batal", callback_data="cancel_backup")]
            ])
        )
    except Exception as e:
        await message.reply_text(f"❌ Gagal mendapatkan info channel sumber: {str(e)}\n\nCoba lagi dengan format yang benar.")


async def _process_backup_target(client: Client, message: Message, text: str):
    """Process target channel input for backup"""
    user_id = message.from_user.id
    backup_data = backup_sessions[user_id]
    userbot_client = backup_data.get("client")
    
    # Ensure userbot client is available
    if not userbot_client:
        # Try to reload from active_userbots
        for session_name, ub_client in active_userbots.items():
            if session_name.startswith(f"ubot_{user_id}_"):
                userbot_client = ub_client
                backup_sessions[user_id]["client"] = userbot_client
                break
        
        if not userbot_client:
            return await message.reply_text("❌ Userbot tidak tersedia. Ulangi proses backup.")
    
    # Parse chat from text (username or link)
    chat = text.replace("https://t.me/", "").replace("@", "").strip()
    
    try:
        # Try to get chat info
        chat_info = await userbot_client.get_chat(chat)
        backup_sessions[user_id]["target"] = chat_info.username or chat_info.id
        backup_sessions[user_id]["state"] = "confirming"
        
        source = backup_sessions[user_id]["source"]
        source_info = await userbot_client.get_chat(source)
        
        # Save backup config for future use
        save_backup_config(
            user_id, 
            source, 
            chat_info.username or chat_info.id,
            source_info.title or source_info.first_name,
            chat_info.title or chat_info.first_name
        )
        
        await message.reply_text(
            f"**📋 Konfirmasi Backup**\n\n"
            f"**Source:** `{source_info.title or source_info.first_name}`\n"
            f"**Target:** `{chat_info.title or chat_info.first_name}`\n\n"
            f"Apakah konfigurasi ini benar?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Mulai Backup", callback_data="start_backup")],
                [InlineKeyboardButton("🔁 Ganti Target", callback_data="change_target")],
                [InlineKeyboardButton("❌ Batal", callback_data="cancel_backup")]
            ])
        )
    except Exception as e:
        await message.reply_text(f"❌ Gagal mendapatkan info channel tujuan: {str(e)}\n\nCoba lagi dengan format yang benar.")


# Callback query handler for inline keyboard
@app.on_callback_query()
async def callback_handler(client: Client, callback_query):
    """Handle inline keyboard callbacks"""
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data.startswith("num_"):
        num = data.split("_")[1]
        
        if user_id not in user_code_input:
            return await callback_query.answer("❌ Session login tidak ditemukan. Gunakan /login terlebih dahulu.", show_alert=True)
        
        user_code_input[user_id]["code"] += num
        code = user_code_input[user_id]["code"]
        
        try:
            await callback_query.message.edit_text(
                f"**Masukkan Kode Login**\n\nKode saat ini: `{code}`\n\nKlik tombol angka untuk menambahkan digit.",
                reply_markup=get_numeric_keyboard()
            )
        except Exception:
            pass
        
        await callback_query.answer()
        
    elif data == "backspace":
        if user_id in user_code_input:
            user_code_input[user_id]["code"] = user_code_input[user_id]["code"][:-1]
            code = user_code_input[user_id]["code"]
            
            try:
                await callback_query.message.edit_text(
                    f"**Masukkan Kode Login**\n\nKode saat ini: `{code}`\n\nKlik tombol angka untuk menambahkan digit.",
                    reply_markup=get_numeric_keyboard()
                )
            except Exception:
                pass
        
        await callback_query.answer()
        
    elif data == "submit_code":
        if user_id not in user_code_input:
            return await callback_query.answer("❌ Session login tidak ditemukan.", show_alert=True)
        
        code = user_code_input[user_id]["code"]
        
        if not code:
            return await callback_query.answer("❌ Masukkan kode terlebih dahulu!", show_alert=True)
        
        await callback_query.answer("⏳ Memverifikasi kode...", show_alert=False)
        
        success, result_msg, user_client, session_name = await verify_login_code(user_id, code)
        
        if success:
            active_userbots[session_name] = user_client
        elif "2FA" in result_msg:
            del user_code_input[user_id]
        
        try:
            await callback_query.message.edit_text(result_msg, reply_markup=get_cancel_keyboard())
        except Exception:
            await callback_query.message.reply_text(result_msg)
            
    elif data == "request_contact":
        await callback_query.answer(
            "Silakan kirim kontak Anda dengan mengklik ikon paperclip 👇 lalu pilih 'Contact'",
            show_alert=True
        )
    
    elif data.startswith("ubot_"):
        phone = data.replace("ubot_", "")
        if phone.startswith("62"):
            phone = "+" + phone
        
        await callback_query.answer(
            f"UserBot {phone} dipilih. Kirim perintah yang ingin dijalankan.",
            show_alert=True
        )
        await callback_query.message.reply_text(
            f"**UserBot Aktif: {phone}**\n\nKirim pesan untuk diproses oleh userbot ini."
        )
        
        # Store selected userbot for potential backup use
        if user_id in backup_sessions and not backup_sessions[user_id].get("client"):
            session_name = f"ubot_{user_id}_{phone.replace('+', '')}"
            if session_name in active_userbots:
                backup_sessions[user_id]["client"] = active_userbots[session_name]
                backup_sessions[user_id]["state"] = "waiting_source"
    
    elif data.startswith("backup_ubot_"):
        # Handle backup userbot selection
        phone = data.replace("backup_ubot_", "")
        if phone.startswith("62"):
            phone = "+" + phone
        
        session_name = f"ubot_{user_id}_{phone.replace('+', '').replace(' ', '')}"
        
        # Try to get existing client or load from database
        userbot_client = active_userbots.get(session_name)
        
        if not userbot_client and db_initialized:
            # Load session from database
            session_string = load_session_from_db_sync(user_id, phone.replace("+", ""))
            if session_string:
                try:
                    userbot_client = Client(
                        session_name,
                        api_id=API_ID,
                        api_hash=API_HASH,
                        session_string=session_string,
                        in_memory=True
                    )
                    await userbot_client.connect()
                    await userbot_client.get_me()
                    active_userbots[session_name] = userbot_client
                except Exception as e:
                    logger.error(f"Failed to load session from DB: {e}")
                    userbot_client = None
        
        if not userbot_client:
            return await callback_query.answer(
                "❌ Userbot tidak aktif atau tidak ditemukan. Login ulang diperlukan.",
                show_alert=True
            )
        
        backup_sessions[user_id] = {
            "client": userbot_client,
            "source": None,
            "target": None,
            "state": "waiting_source"
        }
        
        await callback_query.message.edit_text(
            f"**📥 Backup Media UserBot**\n\n"
            f"Userbot: 🤖 {phone}\n\n"
            f"Silakan kirim **username atau link** channel/group sumber:\n\n"
            f"Contoh: `@mychannel` atau `https://t.me/mychannel`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Batal", callback_data="cancel_backup")]
            ])
        )
    
    elif data == "new_backup":
        sessions = get_user_sessions(user_id)
        if len(sessions) > 1:
            keyboard = []
            for phone in sessions:
                keyboard.append([InlineKeyboardButton(f"🤖 {phone}", callback_data=f"backup_ubot_{phone}")])
            keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="cancel_backup")])
            return await callback_query.message.edit_text(
                "**📥 Backup Media UserBot**\n\nPilih akun userbot:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        if sessions:
            session_name = f"ubot_{user_id}_{sessions[0].replace('+', '').replace(' ', '')}"
            userbot_client = active_userbots.get(session_name)
            if not userbot_client and db_initialized:
                session_string = load_session_from_db_sync(user_id, sessions[0].replace("+", ""))
                if session_string:
                    try:
                        userbot_client = Client(session_name, api_id=API_ID, api_hash=API_HASH, session_string=session_string, in_memory=True)
                        await userbot_client.connect()
                        await userbot_client.get_me()
                        active_userbots[session_name] = userbot_client
                    except Exception:
                        pass
            
            if userbot_client:
                backup_sessions[user_id] = {"client": userbot_client, "source": None, "target": None, "state": "waiting_source"}
                return await callback_query.message.edit_text(
                    "**📥 Backup Media UserBot**\n\nKirim channel sumber:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Batal", callback_data="cancel_backup")]])
                )
        return await callback_query.answer("❌ Tidak ada userbot tersedia.", show_alert=True)
    
    elif data.startswith("quick_backup_"):
        # Quick backup using saved config
        parts = data.replace("quick_backup_", "").split("|")
        if len(parts) != 2:
            return await callback_query.answer("❌ Config tidak valid.", show_alert=True)
        
        source, target = parts
        
        # Find active userbot
        sessions = get_user_sessions(user_id)
        userbot_client = None
        for phone in sessions:
            session_name = f"ubot_{user_id}_{phone.replace('+', '').replace(' ', '')}"
            if session_name in active_userbots:
                userbot_client = active_userbots[session_name]
                break
        
        if not userbot_client and db_initialized and sessions:
            session_string = load_session_from_db_sync(user_id, sessions[0].replace("+", ""))
            if session_string:
                try:
                    session_name = f"ubot_{user_id}_{sessions[0].replace('+', '').replace(' ', '')}"
                    userbot_client = Client(session_name, api_id=API_ID, api_hash=API_HASH, session_string=session_string, in_memory=True)
                    await userbot_client.connect()
                    await userbot_client.get_me()
                    active_userbots[session_name] = userbot_client
                except Exception:
                    pass
        
        if not userbot_client:
            return await callback_query.answer("❌ Userbot tidak aktif.", show_alert=True)
        
        await callback_query.answer("⏳ Memulai backup...", show_alert=False)
        
        asyncio.create_task(_run_backup_process(user_id, userbot_client, source, target))
    
    elif data == "refresh_ubots":
        sessions = get_user_sessions(user_id)
        await callback_query.message.edit_text(
            f"📱 **Akun UserBot yang tersimpan:**\n\n" + "\n".join(f"• `{a}`" for a in sessions) if sessions else "❌ Tidak ada akun yang tersimpan.",
            reply_markup=get_userbot_list_keyboard(user_id, sessions)
        )
    
    elif data == "cancel_login":
        cancelled = False
        
        if user_id in pending_logins:
            login_data = pending_logins[user_id]
            if login_data.get("client"):
                try:
                    await login_data["client"].disconnect()
                except Exception:
                    pass
            del pending_logins[user_id]
            cancelled = True
        
        if user_id in user_code_input:
            del user_code_input[user_id]
            cancelled = True
        
        if cancelled:
            try:
                await callback_query.message.edit_text("✅ Proses login telah dibatalkan.")
            except Exception:
                await callback_query.message.reply_text("✅ Proses login telah dibatalkan.")
        else:
            await callback_query.answer("❌ Tidak ada proses login yang sedang berjalan.", show_alert=True)
    
    # Backup callbacks
    elif data == "start_backup":
        if user_id not in backup_sessions:
            return await callback_query.answer("❌ Sesi backup tidak ditemukan.", show_alert=True)
        
        backup_data = backup_sessions[user_id]
        if not backup_data.get("source") or not backup_data.get("target"):
            return await callback_query.answer("❌ Source atau target belum diisi.", show_alert=True)
        
        await callback_query.answer("⏳ Memulai proses backup...", show_alert=False)
        
        # Start backup task in background
        asyncio.create_task(_run_backup_process(user_id, backup_data["client"], backup_data["source"], backup_data["target"]))
        del backup_sessions[user_id]
    
    elif data == "cancel_backup":
        if user_id in backup_sessions:
            del backup_sessions[user_id]
        await callback_query.message.edit_text("✅ Proses backup telah dibatalkan.")
    
    elif data == "change_source":
        if user_id in backup_sessions:
            backup_sessions[user_id]["source"] = None
            backup_sessions[user_id]["state"] = "waiting_source"
        await callback_query.message.edit_text(
            "**📥 Backup Media UserBot**\n\n"
            "Kirim **username atau link** channel/group sumber baru:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Batal", callback_data="cancel_backup")]
            ])
        )
    
    elif data == "change_target":
        if user_id in backup_sessions:
            backup_sessions[user_id]["target"] = None
            backup_sessions[user_id]["state"] = "waiting_target"
        await callback_query.message.edit_text(
            "**📥 Backup Media UserBot**\n\n"
            "Kirim **username atau link** channel/group tujuan baru:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ganti Source", callback_data="change_source")],
                [InlineKeyboardButton("❌ Batal", callback_data="cancel_backup")]
            ])
        )
    else:
        await callback_query.answer()


async def _run_backup_process(user_id: int, userbot_client: Client, source: str, target: str):
    """Run the backup process - forwards all media messages from source to target"""
    try:
        processed = 0
        skipped = 0
        already_backed_up = 0
        
        # Get chat info for progress messages
        source_chat = await userbot_client.get_chat(source)
        target_chat = await userbot_client.get_chat(target)
        
        # Send progress message to user
        progress_msg = await app.send_message(
            user_id,
            f"⏳ **Backup Sedang Berjalan...**\n\n"
            f"**Source:** `{source_chat.title or source_chat.first_name}`\n"
            f"**Target:** `{target_chat.title or target_chat.first_name}`\n\n"
            f"Progress: Menunggu..."
        )
        
        # Collect all media messages first
        all_media_messages = []
        async for message in userbot_client.search_messages(source, limit=1000):
            if _has_media(message):
                all_media_messages.append(message)
        
        # Process and forward media messages
        for message in all_media_messages:
            # Check if already backed up (prevent duplicates)
            mgid = str(message.media_group_id) if message.media_group_id else None
            if await is_message_backed_up(user_id, source, message.id, mgid):
                already_backed_up += 1
                continue
            
            try:
                await message.forward(target)
                processed += 1
                # Mark as backed up
                await mark_message_backed_up(user_id, source, target, message.id, mgid)
            except Exception as e:
                logger.error(f"Failed to forward message: {e}")
                skipped += 1
            
            # Update progress every 25 messages
            if processed % 25 == 0 and processed > 0:
                try:
                    await progress_msg.edit_text(
                        f"⏳ **Backup Sedang Berjalan...**\n\n"
                        f"**Source:** `{source_chat.title or source_chat.first_name}`\n"
                        f"**Target:** `{target_chat.title or target_chat.first_name}`\n\n"
                        f"Progress: {processed} terkirim, {already_backed_up} sudah ada, {skipped} gagal"
                    )
                except Exception:
                    pass
        
        # Final status
        await progress_msg.edit_text(
            f"✅ **Backup Selesai!**\n\n"
            f"**Source:** `{source_chat.title or source_chat.first_name}`\n"
            f"**Target:** `{target_chat.title or target_chat.first_name}`\n\n"
            f"Total: {processed} pesan media terkirim, {already_backed_up} sudah ada, {skipped} gagal"
        )
        
        logger.info(f"Backup completed for user {user_id}: {processed} new, {already_backed_up} existing")
    
    except Exception as e:
        logger.error(f"Backup process error for user {user_id}: {e}")
        try:
            await app.send_message(user_id, f"❌ **Backup Gagal!**\n\nError: {str(e)}")
        except Exception:
            pass


def _has_media(message) -> bool:
    """Check if message contains any media content (including albums)"""
    # Check for media group (album)
    if message.media_group_id:
        return True
    # Check individual media types
    return bool(
        message.photo or 
        message.video or 
        message.document or 
        message.animation or 
        message.audio or 
        message.voice or 
        message.video_note or 
        message.contact or 
        message.location or 
        message.venue or 
        message.sticker or
        message.media
    )


async def _load_sessions_from_db():
    """Load all userbot sessions from database on startup"""
    if not db_initialized:
        return
    
    try:
        from login_helper import SessionModel, db_session_factory
        db_sess = db_session_factory()
        sessions = db_sess.query(SessionModel).all()
        
        for session_record in sessions:
            session_name = f"ubot_{session_record.user_id}_{session_record.phone}"
            try:
                userbot_client = Client(
                    session_name,
                    api_id=API_ID,
                    api_hash=API_HASH,
                    session_string=session_record.session_string,
                    in_memory=True
                )
                # Not connecting here - will connect on demand
                active_userbots[session_name] = userbot_client
                logger.info(f"Loaded session for user {session_record.user_id}, phone {session_record.phone}")
            except Exception as e:
                logger.error(f"Failed to create client for session {session_name}: {e}")
        
        db_sess.close()
        logger.info(f"Loaded {len(sessions)} sessions from database")
    except Exception as e:
        logger.error(f"Failed to load sessions from DB: {e}")


def get_session_string_from_db(user_id: int, phone: str) -> Optional[str]:
    """Get session string from database"""
    if not db_initialized:
        return None
    
    try:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(load_session_from_db(user_id, phone))
    except Exception:
        return None


# Make sessions persist by disconnecting properly
async def _persist_sessions():
    """Export and persist all active sessions to database before shutdown"""
    if not db_initialized:
        return
    
    try:
        from login_helper import save_session_to_db
        for session_name, client in active_userbots.items():
            try:
                session_string = await client.export_session_string()
                # Parse user_id and phone from session_name
                parts = session_name.replace("ubot_", "").split("_")
                if len(parts) >= 2:
                    user_id = int(parts[0])
                    phone = "_".join(parts[1:])  # Handle phone numbers with underscores
                    await save_session_to_db(user_id, phone, session_string)
            except Exception as e:
                logger.error(f"Failed to persist session {session_name}: {e}")
    except Exception as e:
        logger.error(f"Session persistence error: {e}")


if __name__ == "__main__":
    logger.info("Starting UserBot...")
    
    # Load sessions from database on startup
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(_load_sessions_from_db())
    except Exception as e:
        logger.error(f"Startup session load error: {e}")
    
    # Start the bot
    app.run()