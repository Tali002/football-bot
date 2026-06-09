import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import gspread
import jdatetime
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ─── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN = "8640707951:AAHyb2SrDidDjWG6snpOoFpgTS2LjpuAqQA"
SHEET_ID = "1qOdQFgHZMT2IAzbnopbvrOnwVrjXCQgXJech_XnUg1k"
DEADLINE_MINUTES = 10          # بازی‌هایی که کمتر از این دقیقه به شروعشون مونده قبول نمی‌کنه
DATA_START_ROW = 3             # ردیف اول بازی‌ها (1-indexed)
NAME_ROW = 2                   # ردیف اسامی بازیکنان (header دوم)
FIRST_PRED_COL = 5             # ستون E = index 5 (1-indexed)

# conversation states
CHOOSING_GAME, TYPING_SCORE = range(2)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Google Sheets helpers ────────────────────────────────────────────────────
def get_sheet():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        creds_info = json.loads(creds_json)
    else:
        # fallback به فایل محلی
        with open("service_account.json") as f:
            creds_info = json.load(f)

    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).sheet1


def parse_jalali_datetime(date_str: str, time_str: str) -> Optional[datetime]:
    """
    date_str مثل: «پنجشنبه ۲۱ خرداد»
    time_str از داخل پرانتز داخل ستون D مثل: «۲۲:۳۰»
    تبدیل می‌کنه به datetime میلادی
    """
    MONTH_MAP = {
        "فروردین": 1, "اردیبهشت": 2, "خرداد": 3,
        "تیر": 4, "مرداد": 5, "شهریور": 6,
        "مهر": 7, "آبان": 8, "آذر": 9,
        "دی": 10, "بهمن": 11, "اسفند": 12,
    }
    try:
        # نرمال‌سازی اعداد فارسی
        fa_nums = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
        date_str = date_str.translate(fa_nums).strip()
        time_str = time_str.translate(fa_nums).strip()

        parts = date_str.split()
        # ممکنه «پنجشنبه ۲۱ خرداد» یا «۲۱ خرداد» باشه
        day_num = None
        month_num = None
        for p in parts:
            if p.isdigit():
                day_num = int(p)
            elif p in MONTH_MAP:
                month_num = MONTH_MAP[p]

        if day_num is None or month_num is None:
            return None

        hour, minute = map(int, time_str.split(":"))
        jnow = jdatetime.datetime.now()
        year = jnow.year

        jdt = jdatetime.datetime(year, month_num, day_num, hour, minute)
        return jdt.togregorian()
    except Exception as e:
        logger.warning(f"parse error: {e} | date={date_str} | time={time_str}")
        return None


def extract_time_from_game(game_str: str) -> str:
    """از رشته‌ای مثل 'ایران vs نیوزیلند (۰۴:۳۰)' ساعت رو درمیاره"""
    match = re.search(r"\(([۰-۹0-9]{1,2}:[۰-۹0-9]{2})\)", game_str)
    return match.group(1) if match else ""


def get_games_from_sheet(sheet) -> list[dict]:
    """همه ردیف‌های شیت رو می‌خونه و لیست بازی‌ها برمی‌گردونه"""
    all_values = sheet.get_all_values()
    games = []
    for i, row in enumerate(all_values[DATA_START_ROW - 1:], start=DATA_START_ROW):
        if len(row) < 4:
            continue
        date_val = row[2].strip()   # ستون C
        game_val = row[3].strip()   # ستون D
        if not game_val:
            continue
        time_str = extract_time_from_game(game_val)
        game_dt = parse_jalali_datetime(date_val, time_str) if time_str else None
        games.append({
            "row_index": i,        # 1-indexed در شیت
            "date": date_val,
            "game": game_val,
            "datetime": game_dt,
        })
    return games


def is_open_for_prediction(game_dt: Optional[datetime]) -> bool:
    if game_dt is None:
        return True   # اگه تاریخ parse نشد اجازه می‌ده
    now = datetime.now() + timedelta(hours=3, minutes=30)  # تهران UTC+3:30
    return game_dt - now > timedelta(minutes=DEADLINE_MINUTES)


def get_or_create_user_column(sheet, username: str) -> int:
    """
    اسم کاربر رو تو ردیف NAME_ROW پیدا می‌کنه.
    اگه نبود دو ستون جدید اضافه می‌کنه (پیش‌بینی + نتیجه توقعی).
    index برگشتی 1-indexed هست.
    """
    header_row = sheet.row_values(NAME_ROW)
    # جستجو در ستون‌های جفت (E, G, I, ...)
    col_idx = FIRST_PRED_COL
    while col_idx - 1 < len(header_row):
        cell_val = header_row[col_idx - 1] if col_idx - 1 < len(header_row) else ""
        if cell_val.strip() == username:
            return col_idx
        col_idx += 2

    # پیدا نشد — ستون جدید اضافه کن
    new_col = col_idx
    sheet.update_cell(NAME_ROW - 1, new_col, "پیش‌بینی")    # ردیف 1 = header اول
    sheet.update_cell(NAME_ROW, new_col, username)            # ردیف 2 = اسم
    return new_col


def get_user_prediction(sheet, row_index: int, col_index: int) -> str:
    val = sheet.cell(row_index, col_index).value
    return val or ""


def set_user_prediction(sheet, row_index: int, col_index: int, value: str):
    sheet.update_cell(row_index, col_index, value)


# ─── Bot handlers ─────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ سلام!\n\n"
        "با /predict پیش‌بینی بازی‌ها رو ثبت کن.\n"
        "با /mypredictions پیش‌بینی‌های خودت رو ببین."
    )


async def predict_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لیست بازی‌های قابل پیش‌بینی"""
    await update.message.reply_text("⏳ در حال دریافت بازی‌ها...")
    try:
        sheet = get_sheet()
        games = get_games_from_sheet(sheet)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در اتصال به شیت:\n{e}")
        return ConversationHandler.END

    open_games = [g for g in games if is_open_for_prediction(g["datetime"])]

    if not open_games:
        await update.message.reply_text("⏰ هیچ بازی‌ای برای پیش‌بینی باز نیست.")
        return ConversationHandler.END

    username = update.effective_user.username or update.effective_user.first_name
    user_col = get_or_create_user_column(sheet, username)

    keyboard = []
    for g in open_games:
        current = get_user_prediction(sheet, g["row_index"], user_col)
        label = g["game"]
        if current:
            label = f"✏️ {label}  [{current}]"
        keyboard.append([InlineKeyboardButton(label, callback_data=str(g["row_index"]))])

    keyboard.append([InlineKeyboardButton("❌ انصراف", callback_data="cancel")])

    context.user_data["sheet_obj"] = sheet
    context.user_data["games"] = {str(g["row_index"]): g for g in open_games}
    context.user_data["username"] = username
    context.user_data["user_col"] = user_col

    await update.message.reply_text(
        "🏟 بازی مورد نظرت رو انتخاب کن:\n"
        "_(بازی‌هایی که قبلاً پیش‌بینی کردی با ✏️ و نتیجه فعلی نشون داده شدن)_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return CHOOSING_GAME


async def game_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return ConversationHandler.END

    row_index = query.data
    game_info = context.user_data["games"].get(row_index)

    if not game_info:
        await query.edit_message_text("❌ بازی پیدا نشد.")
        return ConversationHandler.END

    # بررسی مجدد deadline (کاربر ممکنه دیر کلیک کرده باشه)
    if not is_open_for_prediction(game_info["datetime"]):
        await query.edit_message_text(
            f"⏰ متأسفم! کمتر از {DEADLINE_MINUTES} دقیقه به شروع بازی مونده.\n"
            "دیگه نمی‌شه پیش‌بینی کرد."
        )
        return ConversationHandler.END

    context.user_data["selected_row"] = int(row_index)
    current = get_user_prediction(
        context.user_data["sheet_obj"],
        int(row_index),
        context.user_data["user_col"]
    )

    msg = f"⚽ *{game_info['game']}*\n📅 {game_info['date']}\n\n"
    if current:
        msg += f"پیش‌بینی فعلی تو: *{current}*\n\n"
    msg += "نتیجه پیش‌بینیت رو بفرست:\nمثال: `۲-۱` یا `0-0`"

    await query.edit_message_text(msg, parse_mode="Markdown")
    return TYPING_SCORE


async def score_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # نرمال‌سازی اعداد فارسی و جداکننده‌ها
    fa_nums = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    text = text.translate(fa_nums)
    text = text.replace("_", "-").replace("–", "-").replace("−", "-")

    # اعتبارسنجی فرمت X-Y
    if not re.fullmatch(r"\d{1,2}-\d{1,2}", text):
        await update.message.reply_text(
            "❌ فرمت نادرسته!\nلطفاً به شکل `۲-۱` یا `0-3` وارد کن.",
            parse_mode="Markdown"
        )
        return TYPING_SCORE

    row_index = context.user_data["selected_row"]
    game_info = context.user_data["games"][str(row_index)]

    # بررسی نهایی deadline
    if not is_open_for_prediction(game_info["datetime"]):
        await update.message.reply_text(
            f"⏰ متأسفم! در حین تایپ کردن، کمتر از {DEADLINE_MINUTES} دقیقه به شروع بازی رسید.\n"
            "پیش‌بینی ذخیره نشد."
        )
        return ConversationHandler.END

    try:
        set_user_prediction(
            context.user_data["sheet_obj"],
            row_index,
            context.user_data["user_col"],
            text
        )
        await update.message.reply_text(
            f"✅ پیش‌بینی ثبت شد!\n\n"
            f"🏟 *{game_info['game']}*\n"
            f"⚽ نتیجه پیش‌بینی تو: *{text}*\n\n"
            "برای ویرایش دوباره /predict بزن.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در ذخیره‌سازی:\n{e}")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ عملیات لغو شد.")
    return ConversationHandler.END


async def my_predictions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش همه پیش‌بینی‌های کاربر"""
    await update.message.reply_text("⏳ در حال دریافت...")
    try:
        sheet = get_sheet()
        games = get_games_from_sheet(sheet)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا:\n{e}")
        return

    username = update.effective_user.username or update.effective_user.first_name
    header_row = sheet.row_values(NAME_ROW)

    # پیدا کردن ستون کاربر
    user_col = None
    col_idx = FIRST_PRED_COL
    while col_idx - 1 < len(header_row):
        cell_val = header_row[col_idx - 1] if col_idx - 1 < len(header_row) else ""
        if cell_val.strip() == username:
            user_col = col_idx
            break
        col_idx += 2

    if user_col is None:
        await update.message.reply_text("هنوز هیچ پیش‌بینی‌ای ثبت نکردی! /predict بزن.")
        return

    lines = [f"📋 پیش‌بینی‌های *{username}*:\n"]
    for g in games:
        pred = get_user_prediction(sheet, g["row_index"], user_col)
        if pred:
            status = "🔒" if not is_open_for_prediction(g["datetime"]) else "🟢"
            lines.append(f"{status} {g['game']}\n   ↳ نتیجه: *{pred}*")

    if len(lines) == 1:
        await update.message.reply_text("هنوز هیچ پیش‌بینی‌ای ثبت نکردی! /predict بزن.")
        return

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("predict", predict_start)],
        states={
            CHOOSING_GAME: [CallbackQueryHandler(game_chosen)],
            TYPING_SCORE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, score_received)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mypredictions", my_predictions))
    app.add_handler(conv_handler)

    logger.info("Bot started...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
