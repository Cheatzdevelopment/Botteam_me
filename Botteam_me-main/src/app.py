# -*- coding: utf-8 -*-
"""
Real Estate Telegram Bot - Khmer
Features:
- /start shows project guide and property choices
- Select: Borey, Villa, Rental House
- View price, size, payment type
- Collect customer: name, phone, current address, visit date
- Save leads to SQLite database
- Check old/new users and save customer profile

Install:
  pip install python-telegram-bot python-dotenv

.env:
  TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
  ADMIN_PHONE=012345678

Run:
  python real_estate_telegram_bot.py
"""

import os
import sqlite3
import datetime
import logging
from pathlib import Path
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# =========================
# Config
# =========================
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "012 345 678").strip()
DB_PATH = Path(os.getenv("DB_PATH", "real_estate_leads.db")).resolve()

BOT_NAME = "Real Estate Bot"
DIV = "━━━━━━━━━━━━━━━━━━━━"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states
NAME, PHONE, ADDRESS, VISIT_DATE = range(4)

# =========================
# Property Data
# =========================
PROPERTIES = {
    "borey": {
        "title": "🏘️ បុរី",
        "desc": "ផ្ទះបុរីសម្រាប់គ្រួសារ មានទីតាំងល្អ សុវត្ថិភាព និងងាយស្រួលរស់នៅ។",
        "items": [
            {"name": "ផ្ទះល្វែង LA", "price": "$58,000", "size": "4m × 16m", "bed": "2 បន្ទប់គេង", "area": "64㎡"},
            {"name": "ផ្ទះអាជីវកម្ម SH", "price": "$98,000", "size": "4.2m × 18m", "bed": "3 បន្ទប់គេង", "area": "75.6㎡"},
            {"name": "Twin Villa", "price": "$168,000", "size": "8m × 20m", "bed": "4 បន្ទប់គេង", "area": "160㎡"},
        ],
    },
    "villa": {
        "title": "🏡 វីឡា",
        "desc": "វីឡាទំនើប ស្អាត ប្រណិត សាកសមសម្រាប់គ្រួសារធំ និងការរស់នៅបែបឯកជន។",
        "items": [
            {"name": "វីឡាកូនកាត់", "price": "$145,000", "size": "7m × 20m", "bed": "4 បន្ទប់គេង", "area": "140㎡"},
            {"name": "Queen Villa", "price": "$280,000", "size": "12m × 25m", "bed": "5 បន្ទប់គេង", "area": "300㎡"},
            {"name": "King Villa", "price": "$450,000", "size": "15m × 30m", "bed": "6 បន្ទប់គេង", "area": "450㎡"},
        ],
    },
    "rent": {
        "title": "🏠 ផ្ទះជួល",
        "desc": "ផ្ទះជួលតម្លៃសមរម្យ សម្រាប់ស្នាក់នៅ ឬធ្វើអាជីវកម្ម។",
        "items": [
            {"name": "បន្ទប់ជួល", "price": "$80 / ខែ", "size": "4m × 5m", "bed": "1 បន្ទប់", "area": "20㎡"},
            {"name": "ផ្ទះជួលគ្រួសារ", "price": "$250 / ខែ", "size": "4m × 16m", "bed": "2 បន្ទប់គេង", "area": "64㎡"},
            {"name": "ផ្ទះជួលអាជីវកម្ម", "price": "$500 / ខែ", "size": "5m × 20m", "bed": "3 បន្ទប់", "area": "100㎡"},
        ],
    },
}

PAYMENTS = {
    "full": "💵 បង់ប្រាក់ពេញ",
    "installment": "🏦 បង់រំលោះ",
}

# =========================
# Database
# =========================
def db_connect():
    return sqlite3.connect(DB_PATH)


def init_database() -> None:
    """Create/upgrade database tables for users + leads."""
    with db_connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                telegram_name TEXT,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                phone TEXT,
                address TEXT,
                first_seen TEXT,
                last_seen TEXT,
                lead_count INTEGER DEFAULT 0,
                is_old_user INTEGER DEFAULT 0
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                telegram_name TEXT,
                user_status TEXT,
                property_type TEXT,
                property_name TEXT,
                property_price TEXT,
                property_size TEXT,
                payment_type TEXT,
                customer_name TEXT,
                phone TEXT,
                address TEXT,
                visit_date TEXT,
                created_at TEXT
            )
            """
        )

        # Auto-upgrade older database files without deleting data.
        lead_cols = {row[1] for row in con.execute("PRAGMA table_info(leads)").fetchall()}
        if "user_status" not in lead_cols:
            con.execute("ALTER TABLE leads ADD COLUMN user_status TEXT DEFAULT 'old'")

        con.commit()


def upsert_user(user) -> str:
    """Save Telegram user and return 'new' or 'old'."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with db_connect() as con:
        row = con.execute(
            "SELECT telegram_id, lead_count FROM users WHERE telegram_id=?",
            (user.id,),
        ).fetchone()
        if row:
            con.execute(
                """
                UPDATE users
                SET telegram_name=?, username=?, first_name=?, last_name=?, last_seen=?, is_old_user=1
                WHERE telegram_id=?
                """,
                (
                    user.full_name,
                    user.username or "",
                    user.first_name or "",
                    user.last_name or "",
                    now,
                    user.id,
                ),
            )
            con.commit()
            return "old"

        con.execute(
            """
            INSERT INTO users(
                telegram_id, telegram_name, username, first_name, last_name,
                first_seen, last_seen, lead_count, is_old_user
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (
                user.id,
                user.full_name,
                user.username or "",
                user.first_name or "",
                user.last_name or "",
                now,
                now,
            ),
        )
        con.commit()
        return "new"


def update_user_contact(telegram_id: int, phone: str, address: str) -> None:
    with db_connect() as con:
        con.execute(
            """
            UPDATE users
            SET phone=?, address=?, last_seen=?, is_old_user=1
            WHERE telegram_id=?
            """,
            (
                phone,
                address,
                datetime.datetime.now().isoformat(timespec="seconds"),
                telegram_id,
            ),
        )
        con.commit()


def get_user_profile(telegram_id: int) -> dict | None:
    with db_connect() as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM users WHERE telegram_id=?",
            (telegram_id,),
        ).fetchone()
        return dict(row) if row else None


def get_last_lead(telegram_id: int) -> dict | None:
    with db_connect() as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM leads WHERE telegram_id=? ORDER BY id DESC LIMIT 1",
            (telegram_id,),
        ).fetchone()
        return dict(row) if row else None


def save_lead(data: dict) -> int:
    now = datetime.datetime.now().isoformat(timespec="seconds")
    user_status = data.get("user_status", "old")
    with db_connect() as con:
        cur = con.execute(
            """
            INSERT INTO leads(
                telegram_id, telegram_name, user_status, property_type, property_name,
                property_price, property_size, payment_type, customer_name,
                phone, address, visit_date, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("telegram_id"),
                data.get("telegram_name"),
                user_status,
                data.get("property_type"),
                data.get("property_name"),
                data.get("property_price"),
                data.get("property_size"),
                data.get("payment_type"),
                data.get("customer_name"),
                data.get("phone"),
                data.get("address"),
                data.get("visit_date"),
                now,
            ),
        )
        con.execute(
            """
            UPDATE users
            SET lead_count = COALESCE(lead_count, 0) + 1,
                phone=?, address=?, last_seen=?, is_old_user=1
            WHERE telegram_id=?
            """,
            (data.get("phone"), data.get("address"), now, data.get("telegram_id")),
        )
        con.commit()
        return int(cur.lastrowid)


def get_stats() -> tuple[int, int, int]:
    with db_connect() as con:
        total_users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_leads = con.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        old_users = con.execute("SELECT COUNT(*) FROM users WHERE is_old_user=1 OR lead_count>0").fetchone()[0]
    return total_users, old_users, total_leads

# =========================
# Keyboards
# =========================
def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🏠 ចាប់ផ្តើម")], [KeyboardButton("☎️ ទំនាក់ទំនង"), KeyboardButton("📊 Total User")]],
        resize_keyboard=True,
        input_field_placeholder="ជ្រើសរើស Menu...",
    )


def property_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏘️ បុរី", callback_data="type:borey")],
            [InlineKeyboardButton("🏡 វីឡា", callback_data="type:villa")],
            [InlineKeyboardButton("🏠 ផ្ទះជួល", callback_data="type:rent")],
            [InlineKeyboardButton("☎️ ទាក់ទងបុគ្គលិក", callback_data="contact")],
            [InlineKeyboardButton("📊 Check Total User", callback_data="stats")],
        ]
    )


def property_list_keyboard(property_type: str) -> InlineKeyboardMarkup:
    rows = []
    for index, item in enumerate(PROPERTIES[property_type]["items"]):
        rows.append([InlineKeyboardButton(f"{item['name']} • {item['price']}", callback_data=f"property:{property_type}:{index}")])
    rows.append([InlineKeyboardButton("🔙 ត្រឡប់ទៅជម្រើស", callback_data="back:types")])
    return InlineKeyboardMarkup(rows)


def payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(PAYMENTS["full"], callback_data="payment:full")],
            [InlineKeyboardButton(PAYMENTS["installment"], callback_data="payment:installment")],
            [InlineKeyboardButton("🔙 ជ្រើសផ្ទះវិញ", callback_data="back:property_list")],
        ]
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ បញ្ចូលព័ត៌មានណាត់មើលផ្ទះ", callback_data="form:start")],
            [InlineKeyboardButton("🔙 ជ្រើសការបង់ប្រាក់វិញ", callback_data="back:payment")],
        ]
    )

# =========================
# Text Builders
# =========================
def welcome_text(first_name: str) -> str:
    return (
        f"👋 សួស្តី {first_name}!\n{DIV}\n"
        "🏡 សូមស្វាគមន៍មកកាន់ Bot ណែនាំគម្រោងផ្ទះ\n\n"
        "នៅទីនេះ អ្នកអាចធ្វើការ៖\n"
        "✅ ជ្រើសរើស បុរី / វីឡា / ផ្ទះជួល\n"
        "✅ មើលតម្លៃ និងទំហំផ្ទះ\n"
        "✅ ជ្រើសបង់ប្រាក់ពេញ ឬបង់រំលោះ\n"
        "✅ បញ្ចូលទីលំនៅបច្ចុប្បន្ន ឈ្មោះ លេខទូរស័ព្ទ\n"
        "✅ កំណត់ថ្ងៃមកមើលផ្ទះដល់ទីតាំង\n\n"
        "👇 សូមជ្រើសរើសប្រភេទដែលអ្នកចង់បាន"
    )



def old_user_text(first_name: str, profile: dict | None, last_lead: dict | None) -> str:
    lead_count = profile.get("lead_count", 0) if profile else 0
    txt = (
        f"👋 សួស្តីម្ដងទៀត {first_name}!\n{DIV}\n"
        "✅ ប្រព័ន្ធបានស្គាល់អ្នកជា *Old User*\n"
        f"📌 ចំនួនសំណើចាស់: {lead_count}\n\n"
    )
    if last_lead:
        txt += (
            "🧾 សំណើចុងក្រោយរបស់អ្នក៖\n"
            f"🏡 {last_lead.get('property_name')}\n"
            f"💰 {last_lead.get('property_price')}\n"
            f"📞 {last_lead.get('phone')}\n"
            f"📅 {last_lead.get('visit_date')}\n\n"
        )
    txt += "👇 អ្នកអាចជ្រើសគម្រោងថ្មី ឬទាក់ទងបុគ្គលិកបាន"
    return txt


def admin_stats_text() -> str:
    total_users, old_users, total_leads = get_stats()
    new_users = max(total_users - old_users, 0)
    return (
        "📊 ស្ថិតិ Bot\n"
        f"{DIV}\n"
        f"👥 Users សរុប: {total_users}\n"
        f"🆕 New users: {new_users}\n"
        f"🔁 Old users: {old_users}\n"
        f"🧾 Leads សរុប: {total_leads}"
    )

def property_type_text(property_type: str) -> str:
    data = PROPERTIES[property_type]
    return f"{data['title']}\n{DIV}\n{data['desc']}\n\n👇 សូមជ្រើសរើសគម្រោង/ម៉ូឌែលខាងក្រោម៖"


def property_detail_text(property_type: str, index: int) -> str:
    item = PROPERTIES[property_type]["items"][index]
    return (
        f"🏡 {item['name']}\n{DIV}\n"
        f"💰 តម្លៃ: {item['price']}\n"
        f"📐 ទំហំដី/ផ្ទះ: {item['size']}\n"
        f"📏 ផ្ទៃសរុប: {item['area']}\n"
        f"🛏️ {item['bed']}\n\n"
        "👇 សូមជ្រើសរើសរបៀបបង់ប្រាក់"
    )


def summary_text(data: dict) -> str:
    return (
        "📋 សេចក្តីសង្ខេបការជ្រើសរើស\n"
        f"{DIV}\n"
        f"🏷️ ប្រភេទ: {data.get('property_type_title')}\n"
        f"🏡 ផ្ទះ: {data.get('property_name')}\n"
        f"💰 តម្លៃ: {data.get('property_price')}\n"
        f"📐 ទំហំ: {data.get('property_size')}\n"
        f"💳 ការបង់ប្រាក់: {data.get('payment_type')}\n\n"
        "បន្ទាប់មក សូមបញ្ចូលព័ត៌មានរបស់អ្នក ដើម្បីឲ្យបុគ្គលិកទាក់ទង និងណាត់ថ្ងៃមកមើលផ្ទះ។"
    )


def final_text(data: dict, lead_id: int) -> str:
    return (
        "✅ បានទទួលព័ត៌មានរបស់អ្នករួចហើយ!\n"
        f"{DIV}\n"
        f"🧾 លេខសំណើ: #{lead_id}\n"
        f"👤 ឈ្មោះ: {data.get('customer_name')}\n"
        f"📞 ទូរស័ព្ទ: {data.get('phone')}\n"
        f"📍 ទីលំនៅបច្ចុប្បន្ន: {data.get('address')}\n"
        f"📅 ថ្ងៃមកមើលផ្ទះ: {data.get('visit_date')}\n\n"
        f"☎️ សម្រាប់ព័ត៌មានបន្ថែម សូមទាក់ទង: {ADMIN_PHONE}\n\n"
        "អរគុណច្រើន សម្រាប់ការចាប់អារម្មណ៍លើគម្រោងរបស់យើង 🙏"
    )

# =========================
# Handlers
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    context.user_data.clear()
    user_status = upsert_user(user)
    context.user_data["user_status"] = user_status

    if user_status == "new":
        await update.message.reply_text(
            "🆕 អ្នកជា New User — ព័ត៌មានរបស់អ្នកត្រូវបានរក្សាទុកហើយ។",
            reply_markup=main_reply_keyboard(),
        )
        await update.message.reply_text(welcome_text(user.first_name), reply_markup=main_reply_keyboard())
    else:
        profile = get_user_profile(user.id)
        last_lead = get_last_lead(user.id)
        await update.message.reply_text(old_user_text(user.first_name, profile, last_lead), parse_mode="Markdown", reply_markup=main_reply_keyboard())

    await update.message.reply_text("📌 ជ្រើសរើសប្រភេទផ្ទះ៖", reply_markup=property_type_keyboard())


async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "☎️ ព័ត៌មានទំនាក់ទំនង\n"
        f"{DIV}\n"
        f"📞 លេខទូរស័ព្ទ: {ADMIN_PHONE}\n"
        "⏰ ម៉ោងធ្វើការ: 8:00 AM - 6:00 PM\n"
        "📍 អ្នកអាចណាត់មកមើលផ្ទះតាម Bot នេះបាន។"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg, reply_markup=property_type_keyboard())
    else:
        await update.message.reply_text(msg, reply_markup=main_reply_keyboard())


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "stats":
        await query.edit_message_text(admin_stats_text(), reply_markup=property_type_keyboard())
        return ConversationHandler.END

    if data == "contact":
        await contact(update, context)
        return ConversationHandler.END

    if data == "back:types":
        await query.edit_message_text("📌 ជ្រើសរើសប្រភេទផ្ទះ៖", reply_markup=property_type_keyboard())
        return ConversationHandler.END

    if data == "back:property_list":
        property_type = context.user_data.get("property_type", "borey")
        await query.edit_message_text(property_type_text(property_type), reply_markup=property_list_keyboard(property_type))
        return ConversationHandler.END

    if data == "back:payment":
        property_type = context.user_data.get("property_type")
        index = context.user_data.get("property_index", 0)
        await query.edit_message_text(property_detail_text(property_type, index), reply_markup=payment_keyboard())
        return ConversationHandler.END

    if data.startswith("type:"):
        property_type = data.split(":", 1)[1]
        context.user_data["property_type"] = property_type
        context.user_data["property_type_title"] = PROPERTIES[property_type]["title"]
        await query.edit_message_text(property_type_text(property_type), reply_markup=property_list_keyboard(property_type))
        return ConversationHandler.END

    if data.startswith("property:"):
        _, property_type, index_s = data.split(":")
        index = int(index_s)
        item = PROPERTIES[property_type]["items"][index]
        context.user_data.update(
            {
                "property_type": property_type,
                "property_type_title": PROPERTIES[property_type]["title"],
                "property_index": index,
                "property_name": item["name"],
                "property_price": item["price"],
                "property_size": item["size"],
            }
        )
        await query.edit_message_text(property_detail_text(property_type, index), reply_markup=payment_keyboard())
        return ConversationHandler.END

    if data.startswith("payment:"):
        payment_key = data.split(":", 1)[1]
        context.user_data["payment_type"] = PAYMENTS[payment_key]
        await query.edit_message_text(summary_text(context.user_data), reply_markup=confirm_keyboard())
        return ConversationHandler.END

    if data == "form:start":
        await query.edit_message_text("👤 សូមបញ្ចូលឈ្មោះពេញរបស់អ្នក៖")
        return NAME

    return ConversationHandler.END


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("⚠️ សូមបញ្ចូលឈ្មោះឲ្យបានត្រឹមត្រូវ។")
        return NAME
    context.user_data["customer_name"] = name
    await update.message.reply_text("📞 សូមបញ្ចូលលេខទូរស័ព្ទរបស់អ្នក៖")
    return PHONE


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    if len(phone) < 8:
        await update.message.reply_text("⚠️ លេខទូរស័ព្ទមិនត្រឹមត្រូវ។ សូមបញ្ចូលម្ដងទៀត។")
        return PHONE
    context.user_data["phone"] = phone
    await update.message.reply_text("📍 សូមបញ្ចូលទីលំនៅបច្ចុប្បន្នរបស់អ្នក៖")
    return ADDRESS


async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    address = update.message.text.strip()
    if len(address) < 5:
        await update.message.reply_text("⚠️ សូមបញ្ចូលអាសយដ្ឋានឲ្យបានច្បាស់។")
        return ADDRESS
    context.user_data["address"] = address
    await update.message.reply_text("📅 សូមបញ្ជាក់ថ្ងៃដែលចង់មកមើលផ្ទះដល់ទីតាំង\nឧទាហរណ៍: 25/05/2026 ម៉ោង 9:00 ព្រឹក")
    return VISIT_DATE


async def get_visit_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    visit_date = update.message.text.strip()
    if len(visit_date) < 4:
        await update.message.reply_text("⚠️ សូមបញ្ចូលថ្ងៃ/ម៉ោងឲ្យបានច្បាស់។")
        return VISIT_DATE

    user = update.effective_user
    context.user_data["visit_date"] = visit_date
    context.user_data["telegram_id"] = user.id
    context.user_data["telegram_name"] = user.full_name
    context.user_data.setdefault("user_status", "old")

    update_user_contact(user.id, context.user_data.get("phone", ""), context.user_data.get("address", ""))
    lead_id = save_lead(context.user_data)
    await update.message.reply_text(final_text(context.user_data, lead_id), reply_markup=main_reply_keyboard())
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ បានបោះបង់។ ចុច /start ដើម្បីចាប់ផ្តើមម្ដងទៀត។", reply_markup=main_reply_keyboard())
    return ConversationHandler.END


async def text_shortcut(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if text == "🏠 ចាប់ផ្តើម":
        await start(update, context)
    elif text == "☎️ ទំនាក់ទំនង":
        await contact(update, context)
    elif text == "📊 Total User":
        await stats_command(update, context)
    else:
        await update.message.reply_text("សូមចុច /start ដើម្បីមើលជម្រើសផ្ទះ។", reply_markup=main_reply_keyboard())



async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(admin_stats_text(), reply_markup=main_reply_keyboard())

def validate_env() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("❌ សូមដាក់ TELEGRAM_BOT_TOKEN ក្នុង file .env")


def main() -> None:
    validate_env()
    init_database()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)],
            VISIT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_visit_date)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_shortcut))

    print(f"""
╔══════════════════════════════════════╗
  {BOT_NAME} — RUNNING ✅
  Database : {DB_PATH}
  Contact  : {ADMIN_PHONE}
  Button   : 📊 Total User
╚══════════════════════════════════════╝
""")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
