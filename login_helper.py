"""
Multi-Account Login Handler for Telegram UserBot
Supports both file-based and database (Supabase/PostgreSQL) session storage
"""
import os
import logging
import asyncio
from typing import Optional, Tuple
from pyrogram import Client
from pyrogram.errors import (
    ApiIdInvalid,
    PhoneNumberInvalid,
    PhoneCodeInvalid,
    SessionPasswordNeeded,
    PhoneCodeExpired,
)

# Try to import SQLAlchemy for database support
try:
    from sqlalchemy import create_engine, Column, String, DateTime, Integer, Index
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.exc import SQLAlchemyError
    from pyrogram.errors.exceptions.unauthorized_401 import SessionRevoked
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False

logger = logging.getLogger(__name__)

# Pending login sessions
pending_logins = {}

# Database session storage
db_engine = None
db_session_factory = None
SessionModel = None
BackupProgressModel = None
BackupConfigModel = None

# Environment variable for database URL
DATABASE_URL = os.getenv("DATABASE_URL")


def init_database():
    """Initialize database connection and create tables"""
    global db_engine, db_session_factory, SessionModel, BackupProgressModel, BackupConfigModel
    
    if not SQLALCHEMY_AVAILABLE:
        logger.warning("SQLAlchemy not available. Install with: pip install sqlalchemy psycopg2-binary")
        return False
    
    if not DATABASE_URL:
        logger.info("DATABASE_URL not set. Using file-based sessions.")
        return False
    
    try:
        db_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        db_session_factory = sessionmaker(bind=db_engine)
        
        Base = declarative_base()
        
        class UserbotSession(Base):
            __tablename__ = "userbot_sessions"
            __table_args__ = (
                Index("idx_userbot_sessions_unique", "user_id", "phone", unique=True),
            )
            
            id = Column(Integer, primary_key=True)
            user_id = Column(Integer, nullable=False)
            phone = Column(String, nullable=False)
            session_string = Column(String, nullable=False)
            
            def __repr__(self):
                return f"<UserbotSession(user_id={self.user_id}, phone='{self.phone}')>"
        
        class BackupProgress(Base):
            __tablename__ = "backup_progress"
            __table_args__ = (
                Index("idx_backup_progress_lookup", "user_id", "source_chat", "message_id", "media_group_id"),
            )
            
            id = Column(Integer, primary_key=True)
            user_id = Column(Integer, nullable=False)
            source_chat = Column(String, nullable=False)
            target_chat = Column(String, nullable=False)
            message_id = Column(Integer, nullable=False)
            media_group_id = Column(String, nullable=True)
            created_at = Column(DateTime, server_default="NOW()")
            
            def __repr__(self):
                return f"<BackupProgress(user_id={self.user_id}, msg_id={self.message_id})>"
        
        class BackupConfig(Base):
            __tablename__ = "backup_configs"
            __table_args__ = (
                Index("idx_backup_configs_user", "user_id"),
                Index("idx_backup_configs_unique", "user_id", "source_chat", "target_chat", unique=True),
            )
            
            id = Column(Integer, primary_key=True)
            user_id = Column(Integer, nullable=False)
            source_chat = Column(String, nullable=False)
            target_chat = Column(String, nullable=False)
            source_title = Column(String, nullable=True)
            target_title = Column(String, nullable=True)
            created_at = Column(DateTime, server_default="NOW()")
            
            def __repr__(self):
                return f"<BackupConfig(user_id={self.user_id}, source='{self.source_chat}' -> target='{self.target_chat}')>"
        
        SessionModel = UserbotSession
        BackupProgressModel = BackupProgress
        BackupConfigModel = BackupConfig
        Base.metadata.create_all(db_engine)
        logger.info("Database initialized successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        return False


def get_user_sessions_sync(user_id: int) -> list:
    """Get list of session phones for a user - sync version"""
    accounts = []
    
    # Try database first
    if SessionModel and db_session_factory:
        try:
            db_session = db_session_factory()
            sessions = db_session.query(SessionModel).filter(SessionModel.user_id == user_id).all()
            for s in sessions:
                phone = s.phone
                if phone.startswith("62"):
                    phone = "+" + phone
                accounts.append(phone)
            db_session.close()
            return accounts
        except Exception as e:
            logger.error(f"Database query error: {e}")
    
    # Fallback to file-based
    for filename in os.listdir("."):
        if filename.startswith(f"ubot_{user_id}_") and filename.endswith(".session"):
            phone = filename.replace(f"ubot_{user_id}_", "").replace(".session", "")
            if phone.startswith("62"):
                phone = "+" + phone
            accounts.append(phone)
    return accounts


async def get_user_sessions(user_id: int) -> list:
    """Get list of session phones for a user - async wrapper"""
    return await asyncio.to_thread(get_user_sessions_sync, user_id)


async def save_session_to_db(user_id: int, phone: str, session_string: str):
    """Save session string to database - updates existing or creates new"""
    return await asyncio.to_thread(_save_session_to_db_sync, user_id, phone, session_string)


def _save_session_to_db_sync(user_id: int, phone: str, session_string: str) -> bool:
    """Save session string to database - sync version"""
    if not SessionModel or not db_session_factory:
        return False
    
    try:
        db_session = db_session_factory()
        clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
        
        # Check if record exists, update or create
        existing = db_session.query(SessionModel).filter(
            SessionModel.user_id == user_id,
            SessionModel.phone == clean_phone
        ).first()
        
        if existing:
            existing.session_string = session_string
        else:
            session_record = SessionModel(user_id=user_id, phone=clean_phone, session_string=session_string)
            db_session.add(session_record)
        
        db_session.commit()
        db_session.close()
        return True
    except Exception as e:
        logger.error(f"Failed to save session to DB: {e}")
        return False


def load_session_from_db_sync(user_id: int, phone: str) -> Optional[str]:
    """Synchronous wrapper for loading session string from database"""
    if not SessionModel or not db_session_factory:
        return None
    
    try:
        db_session = db_session_factory()
        clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
        session_record = db_session.query(SessionModel).filter(
            SessionModel.user_id == user_id,
            SessionModel.phone == clean_phone
        ).first()
        db_session.close()
        return session_record.session_string if session_record else None
    except Exception as e:
        logger.error(f"Failed to load session from DB: {e}")
        return None


async def load_session_from_db(user_id: int, phone: str) -> Optional[str]:
    """Load session string from database"""
    return load_session_from_db_sync(user_id, phone)


async def is_message_backed_up(user_id: int, source_chat: str, message_id: int, media_group_id: Optional[str] = None) -> bool:
    """Check if a message was already backed up - runs in thread pool to avoid blocking"""
    return await asyncio.to_thread(is_message_backed_up_sync, user_id, source_chat, message_id, media_group_id)


def is_message_backed_up_sync(user_id: int, source_chat: str, message_id: int, media_group_id: Optional[str] = None) -> bool:
    """Synchronous version - Check if a message was already backed up"""
    global BackupProgressModel
    if not BackupProgressModel or not db_session_factory:
        return False
    
    try:
        db_session = db_session_factory()
        query = db_session.query(BackupProgressModel).filter(
            BackupProgressModel.user_id == user_id,
            BackupProgressModel.source_chat == source_chat,
            BackupProgressModel.message_id == message_id
        )
        if media_group_id:
            query = query.filter(BackupProgressModel.media_group_id == media_group_id)
        exists = query.first() is not None
        db_session.close()
        return exists
    except Exception as e:
        logger.error(f"Failed to check backup progress: {e}")
        return False


async def mark_message_backed_up(user_id: int, source_chat: str, target_chat: str, message_id: int, media_group_id: Optional[str] = None):
    """Mark a message as backed up in database - runs in thread pool to avoid blocking"""
    return await asyncio.to_thread(mark_message_backed_up_sync, user_id, source_chat, target_chat, message_id, media_group_id)


def mark_message_backed_up_sync(user_id: int, source_chat: str, target_chat: str, message_id: int, media_group_id: Optional[str] = None):
    """Synchronous version - Mark a message as backed up in database"""
    global BackupProgressModel
    if not BackupProgressModel or not db_session_factory:
        return False
    
    try:
        db_session = db_session_factory()
        record = BackupProgressModel(
            user_id=user_id,
            source_chat=source_chat,
            target_chat=target_chat,
            message_id=message_id,
            media_group_id=media_group_id
        )
        db_session.add(record)
        db_session.commit()
        db_session.close()
        return True
    except Exception as e:
        logger.error(f"Failed to mark backup progress: {e}")
        return False


def clear_backup_progress(user_id: int, source_chat: str, target_chat: str):
    """Clear backup progress to allow re-backup (for force backup)"""
    global BackupProgressModel
    if not BackupProgressModel or not db_session_factory:
        return False
    
    try:
        db_session = db_session_factory()
        db_session.query(BackupProgressModel).filter(
            BackupProgressModel.user_id == user_id,
            BackupProgressModel.source_chat == source_chat,
            BackupProgressModel.target_chat == target_chat
        ).delete()
        db_session.commit()
        db_session.close()
        return True
    except Exception as e:
        logger.error(f"Failed to clear backup progress: {e}")
        return False


async def save_backup_config(user_id: int, source_chat: str, target_chat: str, source_title: str = None, target_title: str = None):
    """Save backup configuration for quick reuse"""
    return await asyncio.to_thread(_save_backup_config_sync, user_id, source_chat, target_chat, source_title, target_title)


def _save_backup_config_sync(user_id: int, source_chat: str, target_chat: str, source_title: str = None, target_title: str = None) -> bool:
    """Save backup configuration - sync version"""
    global BackupConfigModel
    if not BackupConfigModel or not db_session_factory:
        return False
    
    try:
        db_session = db_session_factory()
        # Check if config already exists
        existing = db_session.query(BackupConfigModel).filter(
            BackupConfigModel.user_id == user_id,
            BackupConfigModel.source_chat == source_chat,
            BackupConfigModel.target_chat == target_chat
        ).first()
        
        if not existing:
            config = BackupConfigModel(
                user_id=user_id,
                source_chat=source_chat,
                target_chat=target_chat,
                source_title=source_title,
                target_title=target_title
            )
            db_session.add(config)
            db_session.commit()
        db_session.close()
        return True
    except Exception as e:
        logger.error(f"Failed to save backup config: {e}")
        return False


async def get_backup_configs(user_id: int) -> list:
    """Get all backup configurations for a user"""
    return await asyncio.to_thread(_get_backup_configs_sync, user_id)


def _get_backup_configs_sync(user_id: int) -> list:
    """Get all backup configurations - sync version"""
    global BackupConfigModel
    if not BackupConfigModel or not db_session_factory:
        return []
    
    try:
        db_session = db_session_factory()
        configs = db_session.query(BackupConfigModel).filter(
            BackupConfigModel.user_id == user_id
        ).order_by(BackupConfigModel.created_at.desc()).all()
        result = []
        for c in configs:
            result.append({
                "source": c.source_chat,
                "target": c.target_chat,
                "source_title": c.source_title,
                "target_title": c.target_title
            })
        db_session.close()
        return result
    except Exception as e:
        logger.error(f"Failed to get backup configs: {e}")
        return []


async def start_login_process(user_id: int, phone: str, api_id: int, api_hash: str) -> tuple[bool, str]:
    """Start the login process for a phone number."""
    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
    session_name = f"ubot_{user_id}_{clean_phone}"
    
    if os.path.exists(f"{session_name}.session"):
        return False, "❌ Akun ini sudah terdaftar. Gunakan `/accounts` untuk melihat daftar akun."
    
    client = Client(
        session_name,
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True
    )
    
    try:
        await client.connect()
        result = await client.send_code(phone)
        
        pending_logins[user_id] = {
            "phone": phone,
            "client": client,
            "phone_code_hash": result.phone_code_hash,
            "api_id": api_id,
            "api_hash": api_hash,
            "session_name": session_name,
            "code": None,
            "needs_2fa": False
        }
        
        logger.info(f"Login process started for phone {phone}")
        return True, "✅ Permintaan login diterima. Silakan cek kode login di akun Telegram Anda, lalu input kode menggunakan tombol di bawah."
        
    except PhoneNumberInvalid:
        return False, "❌ Nomor telepon tidak valid. Pastikan formatnya benar (misal: +628123456789)"
    except ApiIdInvalid:
        return False, "❌ API ID atau API Hash tidak valid"
    except SessionRevoked:
        return False, "❌ Sesi tidak valid. File session mungkin korup. Hapus file session secara manual."
    except Exception as e:
        logger.error(f"Login error for {phone}: {e}")
        return False, f"❌ Gagal memulai proses login: {str(e)}"


async def verify_login_code(user_id: int, code: str) -> tuple[bool, str, Client, str]:
    """Verify the login code and complete authentication."""
    if user_id not in pending_logins:
        return False, "❌ Tidak ada proses login yang pending. Gunakan `/login` terlebih dahulu.", None, None
    
    login_data = pending_logins[user_id]
    client = login_data["client"]
    phone = login_data["phone"]
    phone_code_hash = login_data["phone_code_hash"]
    session_name = login_data["session_name"]
    
    login_data["code"] = code
    
    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        
        # Export session string for database storage
        session_string = await client.export_session_string()
        clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
        
        # Save to database if available
        await save_session_to_db(user_id, clean_phone, session_string)
        
        del pending_logins[user_id]
        
        logger.info(f"Login successful for user {user_id}, phone {phone}")
        return True, f"✅ **Login Berhasil!**\n\nNama: {me.first_name}\nUsername: @{me.username if me.username else 'Tidak ada'}\n\nAkun telah disimpan sebagai userbot.", client, session_name
    
    except PhoneCodeInvalid:
        return False, "❌ Kode salah. Silakan coba lagi.", None, None
    except PhoneCodeExpired:
        return False, "❌ Kode telah kadaluarsa. Gunakan `/login` ulang.", None, None
    except SessionPasswordNeeded:
        login_data["needs_2fa"] = True
        return False, "🔒 Akun ini menggunakan password 2FA. Silakan kirim password Anda sebagi pesan teks ke bot.", None, session_name
    except Exception as e:
        logger.error(f"Verification error for {user_id}: {e}")
        return False, f"❌ Gagal verifikasi: {str(e)}", None, session_name


async def verify_2fa_password(user_id: int, password: str) -> tuple[bool, str, Client, str]:
    """Verify 2FA password for pending login."""
    if user_id not in pending_logins:
        return False, "❌ Tidak ada proses login yang pending.", None, None
    
    login_data = pending_logins[user_id]
    
    if not login_data.get("needs_2fa"):
        return False, "❌ Akun ini tidak memerlukan 2FA. Gunakan `/verify` untuk kode biasa.", None, None
    
    client = login_data["client"]
    phone = login_data["phone"]
    phone_code_hash = login_data["phone_code_hash"]
    code = login_data["code"]
    session_name = login_data["session_name"]
    
    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash, password=password)
        me = await client.get_me()
        
        # Export session string for database storage
        session_string = await client.export_session_string()
        clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
        
        # Save to database if available
        await save_session_to_db(user_id, clean_phone, session_string)
        
        del pending_logins[user_id]
        
        logger.info(f"2FA login successful for user {user_id}, phone {phone}")
        return True, f"✅ **Login Berhasil!**\n\nNama: {me.first_name}\nUsername: @{me.username if me.username else 'Tidak ada'}\n\nAkun telah disimpan sebagi userbot.", client, session_name
    
    except Exception as e:
        if "PASSWORD_HASH_INVALID" in str(e) or "password" in str(e).lower():
            return False, "❌ Password 2FA salah. Silakan kirim password yang benar.", None, None
        
        logger.error(f"2FA verification error for {user_id}: {e}")
        return False, f"❌ Gagal verifikasi 2FA: {str(e)}", None, None