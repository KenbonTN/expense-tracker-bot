import os
import re
import logging
import pytz
from datetime import datetime, date, time
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    filters, ContextTypes, JobQueue
)
import gspread
from google.oauth2.service_account import Credentials

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
SPREADSHEET_ID   = os.environ["SPREADSHEET_ID"]
_BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
_creds_path      = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
CREDENTIALS_FILE = _creds_path if os.path.isabs(_creds_path) else os.path.join(_BASE_DIR, _creds_path)
# Your Telegram user ID — the bot will send alerts/reports to you directly.
# Get it by messaging @userinfobot on Telegram, then paste your ID below.
MY_CHAT_ID       = int(os.environ.get("MY_CHAT_ID", "0"))

# Timezone — change to your local timezone if needed
TIMEZONE = pytz.timezone("Africa/Addis_Ababa")

# Daily spending alert thresholds in ETB
ALERT_THRESHOLDS = [250, 500, 700, 1000]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(format="%(asctime)s  %(levelname)s  %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Categories ────────────────────────────────────────────────────────────────
EXPENSE_CATEGORIES = {
    "food":          ["food", "lunch", "dinner", "breakfast", "coffee", "snack", "eat", "restaurant", "cafe", "injera", "kitfo"],
    "transport":     ["transport", "taxi", "bus", "ride", "uber", "bolt", "minibus", "fuel", "petrol"],
    "groceries":     ["groceries", "grocery", "supermarket", "market", "shopping", "store", "shiro", "teff"],
    "rent":          ["rent", "house", "apartment"],
    "utilities":     ["utilities", "electric", "water", "internet", "wifi", "phone", "bill", "ethio telecom"],
    "health":        ["health", "doctor", "medicine", "pharmacy", "hospital", "clinic"],
    "entertainment": ["entertainment", "movie", "cinema", "game", "fun", "outing", "bar"],
    "education":     ["education", "course", "book", "training", "school", "tuition"],
    "other":         [],
}

INCOME_KEYWORDS  = ["income", "salary", "received", "earned", "got paid", "payment received", "wage", "freelance income"]
SAVINGS_KEYWORDS = ["saved", "saving", "savings", "deposited", "invest", "put aside"]

# ── Google Sheets ─────────────────────────────────────────────────────────────
def get_spreadsheet():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def get_or_create_sheet(spreadsheet, sheet_name: str, rows=1000, cols=10):
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=sheet_name, rows=rows, cols=cols)

# ── Parsing ───────────────────────────────────────────────────────────────────
def detect_type_and_category(text: str):
    lower = text.lower()
    if any(kw in lower for kw in INCOME_KEYWORDS):
        return "income", "income"
    if any(kw in lower for kw in SAVINGS_KEYWORDS):
        return "savings", "savings"
    for cat, keywords in EXPENSE_CATEGORIES.items():
        if any(kw in lower for kw in keywords):
            return "expense", cat
    return "expense", "other"

def parse_message(text: str):
    text = text.strip()
    cleaned = re.sub(r"\b(spent|on|for|etb|birr|usd|eur)\b", "", text, flags=re.IGNORECASE).strip()
    match = re.search(r"\d+(\.\d+)?", cleaned)
    if not match:
        return None
    amount = float(match.group())
    note = re.sub(r"\d+(\.\d+)?", "", cleaned).strip(" ,.-")
    if not note:
        note = "—"
    entry_type, category = detect_type_and_category(text)
    return amount, note, entry_type, category

# ── Sheet data helpers ────────────────────────────────────────────────────────
def get_monthly_data(month_name: str):
    try:
        return get_spreadsheet().worksheet(month_name).get_all_records()
    except Exception:
        return []

def get_today_total():
    """Returns today's total expense amount in ETB."""
    today_str = date.today().strftime("%Y-%m-%d")
    month_name = datetime.now(TIMEZONE).strftime("%B %Y")
    rows = get_monthly_data(month_name)
    total = 0.0
    for row in rows:
        if str(row.get("Date","")) != today_str:
            continue
        if str(row.get("Type","")).lower() != "expense":
            continue
        try:
            total += float(str(row.get("Amount (ETB)", 0)).replace(",", ""))
        except (ValueError, TypeError):
            pass
    return total

def build_daily_summary(target_date_str: str, month_name: str):
    """Returns formatted summary text for a given date."""
    rows = get_monthly_data(month_name)
    total_income = total_saved = total_spent = 0.0
    by_category = defaultdict(float)
    entries = []

    for row in rows:
        if str(row.get("Date","")) != target_date_str:
            continue
        try:
            amt = float(str(row.get("Amount (ETB)", 0)).replace(",", ""))
        except (ValueError, TypeError):
            continue
        t   = str(row.get("Type","expense")).lower()
        cat = str(row.get("Category","other")).lower()
        n   = str(row.get("Note","—"))
        entries.append((t, amt, cat, n))

        if t == "income":    total_income += amt
        elif t == "savings": total_saved  += amt
        else:
            total_spent += amt
            by_category[cat] += amt

    return total_income, total_saved, total_spent, by_category, entries

# ── Log entry ─────────────────────────────────────────────────────────────────
def log_entry(amount: float, note: str, entry_type: str, category: str):
    now = datetime.now(TIMEZONE)
    month_name = now.strftime("%B %Y")
    spreadsheet = get_spreadsheet()

    log_sheet = get_or_create_sheet(spreadsheet, month_name)
    headers = ["Date", "Time", "Type", "Amount (ETB)", "Category", "Note"]
    if log_sheet.row_values(1) != headers:
        log_sheet.insert_row(headers, index=1)
        log_sheet.format("A1:F1", {"textFormat": {"bold": True}})

    log_sheet.append_row([
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M"),
        entry_type.capitalize(),
        amount,
        category.capitalize(),
        note.capitalize(),
    ], value_input_option="USER_ENTERED")

    try:
        refresh_dashboard(spreadsheet, month_name)
    except Exception as e:
        logger.warning("Dashboard refresh failed (entry was saved): %s", e)
    return month_name

# ── Dashboard ─────────────────────────────────────────────────────────────────
def refresh_dashboard(spreadsheet, month_name: str):
    try:
        rows = spreadsheet.worksheet(month_name).get_all_records()
    except Exception:
        return

    total_income = total_saved = total_spent = 0.0
    by_category  = defaultdict(float)
    by_date      = defaultdict(float)
    all_expenses = []

    for row in rows:
        try:
            amt = float(str(row.get("Amount (ETB)", 0)).replace(",", ""))
        except (ValueError, TypeError):
            continue
        t   = str(row.get("Type", "expense")).lower()
        cat = str(row.get("Category", "other")).lower()
        d   = str(row.get("Date", ""))
        n   = str(row.get("Note", ""))

        if t == "income":    total_income += amt
        elif t == "savings": total_saved  += amt
        else:
            total_spent += amt
            by_category[cat] += amt
            by_date[d] += amt
            all_expenses.append((amt, n, d, cat))

    days_active = len(by_date)
    avg_daily   = total_spent / days_active if days_active else 0
    net         = total_income - total_spent - total_saved
    top5        = sorted(all_expenses, key=lambda x: -x[0])[:5]
    today_str   = date.today().strftime("%Y-%m-%d")
    today_spent = by_date.get(today_str, 0)

    dash = get_or_create_sheet(spreadsheet, "📊 Dashboard", rows=60, cols=4)
    dash.clear()

    now_str = datetime.now(TIMEZONE).strftime("%d %b %Y  %H:%M")
    data = [
        ["📊 EXPENSE DASHBOARD", "", f"Last updated: {now_str}", ""],
        ["", "", "", ""],
        ["── MONTHLY OVERVIEW ──", month_name, "", ""],
        ["Total income",  f"{total_income:,.0f} ETB",   "", ""],
        ["Total spent",   f"-{total_spent:,.0f} ETB",   "", ""],
        ["Total saved",   f"{total_saved:,.0f} ETB",    "", ""],
        ["Net balance",   f"{net:+,.0f} ETB",            "", ""],
        ["", "", "", ""],
        ["── DAILY STATS ──", "", "", ""],
        ["Avg daily expense",  f"{avg_daily:,.0f} ETB",   "", ""],
        ["Today's spending",   f"{today_spent:,.0f} ETB", "", ""],
        ["Days tracked",       f"{days_active} days",     "", ""],
        ["", "", "", ""],
        ["── SPENDING BY CATEGORY ──", "", "", ""],
    ]

    for cat, amt in sorted(by_category.items(), key=lambda x: -x[1]):
        pct = (amt / total_spent * 100) if total_spent else 0
        bar = "█" * int(pct / 5)
        data.append([cat.capitalize(), f"{amt:,.0f} ETB", f"{pct:.1f}%", bar])

    data += [["", "", "", ""], ["── TOP 5 BIGGEST EXPENSES ──", "", "", ""]]
    for i, (amt, note, d, cat) in enumerate(top5, 1):
        data.append([f"#{i}  {note.capitalize()}  ({cat})", f"{amt:,.0f} ETB", d, ""])

    data += [["", "", "", ""], ["── SAVINGS RATE ──", "", "", ""]]
    if total_income > 0:
        data.append(["Savings rate", f"{(total_saved/total_income*100):.1f}%", "of income", ""])
        data.append(["Spent rate",   f"{(total_spent/total_income*100):.1f}%",  "of income", ""])
    else:
        data.append(["Log your income to see savings rate", "", "", ""])

    dash.update("A1", data)
    dash.format("A1", {"textFormat": {"bold": True, "fontSize": 13}})
    color = {"red": 0.1, "green": 0.6, "blue": 0.1} if net >= 0 else {"red": 0.8, "green": 0.1, "blue": 0.1}
    dash.format("B7", {"textFormat": {"foregroundColor": color, "bold": True}})

    spreadsheet.batch_update({"requests": [
        {"updateDimensionProperties": {"range": {"sheetId": dash.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 240}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": dash.id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2}, "properties": {"pixelSize": 130}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": dash.id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3}, "properties": {"pixelSize": 90},  "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": dash.id, "dimension": "COLUMNS", "startIndex": 3, "endIndex": 4}, "properties": {"pixelSize": 200}, "fields": "pixelSize"}},
    ]})

# ── Alert logic ───────────────────────────────────────────────────────────────
def check_threshold_crossed(previous_total: float, new_total: float):
    """Returns the threshold just crossed, or None."""
    for threshold in ALERT_THRESHOLDS:
        if previous_total < threshold <= new_total:
            return threshold
    return None

THRESHOLD_MESSAGES = {
    250:  ("🟡", "You've hit 250 ETB today. You're off to a spendy start!"),
    500:  ("🟠", "You've crossed 500 ETB today. Halfway to your daily caution zone."),
    700:  ("🔴", "⚠️ 700 ETB spent today. Consider slowing down for the rest of the day."),
    1000: ("🚨", "🚨 1,000 ETB spent today! That's a heavy day — try to avoid any more non-essentials."),
}

# ── Scheduled jobs ────────────────────────────────────────────────────────────
async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    """Runs at 9PM every day and sends a report to MY_CHAT_ID."""
    if not MY_CHAT_ID:
        return

    now        = datetime.now(TIMEZONE)
    today_str  = now.strftime("%Y-%m-%d")
    month_name = now.strftime("%B %Y")

    total_income, total_saved, total_spent, by_category, entries = build_daily_summary(today_str, month_name)

    if not entries:
        await context.bot.send_message(
            chat_id=MY_CHAT_ID,
            text=f"📅 *Daily Report — {today_str}*\n\nNothing logged today. Clean slate! 🧹",
            parse_mode="Markdown",
        )
        return

    lines = [f"📅 *Daily Report — {today_str}*\n"]

    if total_income > 0:
        lines.append(f"💵 Income:  {total_income:,.0f} ETB")
    lines.append(f"💸 Spent:   {total_spent:,.0f} ETB")
    if total_saved > 0:
        lines.append(f"💰 Saved:   {total_saved:,.0f} ETB")

    if by_category:
        lines.append("\n*By category:*")
        for cat, amt in sorted(by_category.items(), key=lambda x: -x[1]):
            lines.append(f"  • {cat.capitalize()}: {amt:,.0f} ETB")

    lines.append("\n*Entries today:*")
    for t, amt, cat, note in entries:
        icon = "💵" if t == "income" else ("💰" if t == "savings" else "•")
        lines.append(f"  {icon} {note.capitalize()} — {amt:,.0f} ETB")

    # Motivational close
    if total_spent == 0:
        lines.append("\n🌟 Zero expenses today. Amazing discipline!")
    elif total_spent < 250:
        lines.append("\n✅ Great job keeping it light today!")
    elif total_spent < 500:
        lines.append("\n👍 Reasonable day. Keep it up!")
    elif total_spent < 700:
        lines.append("\n⚠️ A bit heavy today. Try to balance tomorrow.")
    else:
        lines.append("\n🔴 High spending day. Review and adjust tomorrow.")

    await context.bot.send_message(
        chat_id=MY_CHAT_ID,
        text="\n".join(lines),
        parse_mode="Markdown",
    )

# ── Telegram handlers ─────────────────────────────────────────────────────────
KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("/summary"), KeyboardButton("/today")],
     [KeyboardButton("/top5"),    KeyboardButton("/help")]],
    resize_keyboard=True,
)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    result = parse_message(text)
    if result is None:
        await update.message.reply_text(
            "❓ Couldn't read that. Try:\n"
            "  `150 lunch`\n"
            "  `income 8000 salary`\n"
            "  `saved 1000`",
            parse_mode="Markdown",
        )
        return

    amount, note, entry_type, category = result

    # Check spending threshold BEFORE logging (to detect crossing)
    prev_total = get_today_total() if entry_type == "expense" else 0

    try:
        month_name = log_entry(amount, note, entry_type, category)
    except Exception as e:
        logger.error("Error logging entry: %s", e)
        await update.message.reply_text(
            f"⚠️ Something went wrong writing to the sheet.\n\n`{type(e).__name__}: {e}`",
            parse_mode="Markdown",
        )
        return

    # Confirm log
    if entry_type == "income":
        emoji, label = "💵", "Income"
    elif entry_type == "savings":
        emoji, label = "💰", "Saved"
    else:
        emoji, label = "✅", f"Spent ({category})"

    await update.message.reply_text(
        f"{emoji} *{label}:* {amount:,.0f} ETB\n"
        f"📝 _{note.capitalize()}_\n"
        f"📄 Logged to _{month_name}_  ·  Dashboard updated",
        parse_mode="Markdown",
        reply_markup=KEYBOARD,
    )

    # Send spending alert if threshold crossed
    if entry_type == "expense":
        new_total = prev_total + amount
        threshold = check_threshold_crossed(prev_total, new_total)
        if threshold:
            emoji_t, msg = THRESHOLD_MESSAGES[threshold]
            await update.message.reply_text(
                f"{emoji_t} *Spending alert!*\n{msg}\n\n"
                f"💸 Total today: *{new_total:,.0f} ETB*",
                parse_mode="Markdown",
            )

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month_name = datetime.now(TIMEZONE).strftime("%B %Y")
    rows = get_monthly_data(month_name)
    if not rows:
        await update.message.reply_text(f"No entries yet for {month_name}.")
        return

    total_income = total_saved = total_spent = 0.0
    by_category = defaultdict(float)
    for row in rows:
        try:
            amt = float(str(row.get("Amount (ETB)", 0)).replace(",", ""))
        except (ValueError, TypeError):
            continue
        t   = str(row.get("Type", "expense")).lower()
        cat = str(row.get("Category", "other")).lower()
        if t == "income":    total_income += amt
        elif t == "savings": total_saved  += amt
        else:
            total_spent += amt
            by_category[cat] += amt

    net = total_income - total_spent - total_saved
    lines = [f"📊 *{month_name}*\n",
             f"💵 Income:  *{total_income:,.0f} ETB*",
             f"💸 Spent:   *{total_spent:,.0f} ETB*",
             f"💰 Saved:   *{total_saved:,.0f} ETB*",
             f"{'🟢' if net >= 0 else '🔴'} Net: *{net:+,.0f} ETB*\n",
             "*By category:*"]
    for cat, amt in sorted(by_category.items(), key=lambda x: -x[1]):
        lines.append(f"  • {cat.capitalize()}: {amt:,.0f} ETB")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TIMEZONE)
    today_str  = now.strftime("%Y-%m-%d")
    month_name = now.strftime("%B %Y")
    _, _, total_spent, by_category, entries = build_daily_summary(today_str, month_name)

    if not entries:
        await update.message.reply_text("Nothing logged today yet.")
        return

    lines = [f"📅 *Today ({today_str})*\n"]
    for t, amt, cat, note in entries:
        icon = "💵" if t == "income" else ("💰" if t == "savings" else "•")
        lines.append(f"  {icon} {note.capitalize()} — {amt:,.0f} ETB")
    lines.append(f"\n💸 Total spent today: *{total_spent:,.0f} ETB*")

    # Show which threshold zone we're in
    if total_spent >= 1000:
        lines.append("🚨 Over 1,000 ETB today!")
    elif total_spent >= 700:
        lines.append("🔴 Over 700 ETB today")
    elif total_spent >= 500:
        lines.append("🟠 Over 500 ETB today")
    elif total_spent >= 250:
        lines.append("🟡 Over 250 ETB today")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_top5(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month_name = datetime.now(TIMEZONE).strftime("%B %Y")
    rows = get_monthly_data(month_name)
    expenses = []
    for r in rows:
        if str(r.get("Type","")).lower() != "expense": continue
        try:
            amt = float(str(r.get("Amount (ETB)", 0)).replace(",", ""))
            expenses.append((amt, r.get("Note","—"), r.get("Date",""), r.get("Category","other")))
        except (ValueError, TypeError):
            continue
    if not expenses:
        await update.message.reply_text("No expenses logged yet this month.")
        return
    top = sorted(expenses, key=lambda x: -x[0])[:5]
    lines = [f"🏆 *Top 5 — {month_name}*\n"]
    for i, (amt, note, d, cat) in enumerate(top, 1):
        lines.append(f"*#{i}* {note.capitalize()} _{cat}_\n    {amt:,.0f} ETB · {d}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 *Expense Tracker Bot*\n\n"
        "*Log expense:*  `150 lunch`  `500 rent`\n"
        "*Log income:*   `income 8000 salary`\n"
        "*Log savings:*  `saved 1000`\n\n"
        "*/summary* — monthly overview\n"
        "*/today*   — today's spending\n"
        "*/top5*    — biggest expenses\n"
        "*/help*    — this message\n\n"
        "🔔 *Alerts* fire when you cross 250, 500, 700, or 1,000 ETB in a day.\n"
        "📩 *Daily report* sent every night at 9 PM.",
        parse_mode="Markdown",
        reply_markup=KEYBOARD,
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "there"
    await update.message.reply_text(
        f"👋 Hey {name}! I'm your personal finance bot.\n\n"
        "Send me things like:\n"
        "  `150 lunch`\n"
        "  `income 8000 salary`\n"
        "  `saved 1000`\n\n"
        "I'll keep your *📊 Dashboard* updated, alert you when spending gets high, "
        "and send you a report every night at 9 PM.\n\n"
        "/help to see all commands.",
        parse_mode="Markdown",
        reply_markup=KEYBOARD,
    )

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Schedule 9 PM daily report
    if MY_CHAT_ID:
        app.job_queue.run_daily(
            send_daily_report,
            time=time(hour=21, minute=0, second=0, tzinfo=TIMEZONE),
            name="daily_report",
        )
        logger.info("Daily report scheduled at 21:00 Africa/Addis_Ababa")
    else:
        logger.warning("MY_CHAT_ID not set — daily report disabled. Add it to your .env file.")

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("today",   cmd_today))
    app.add_handler(CommandHandler("top5",    cmd_top5))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running…")
    app.run_polling()

if __name__ == "__main__":
    main()
