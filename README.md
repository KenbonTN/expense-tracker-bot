# Expense Tracker Bot

A personal finance Telegram bot that logs your expenses, income, and savings directly into a **Google Sheets spreadsheet** — with automatic categorization, spending alerts, a live dashboard, and a nightly summary report.

Built for daily personal use with ETB (Ethiopian Birr) as the default currency, but easily adaptable to any currency or timezone.

---

## Features

- **Natural language logging** — just type `150 lunch` or `income 8000 salary` and the bot figures out the rest
- **Auto-categorization** — detects food, transport, groceries, rent, utilities, health, entertainment, education, and more from your message
- **Live Google Sheets dashboard** — a `📊 Dashboard` sheet is updated on every entry with monthly totals, category breakdowns, top 5 expenses, savings rate, and daily averages
- **Spending alerts** — get notified when your daily spending crosses 250, 500, 700, or 1,000 ETB
- **Daily report at 9 PM** — a nightly summary of everything logged that day, sent directly to you
- **Monthly sheets** — each month gets its own sheet (e.g. `April 2026`) with a clean log of every entry
- **Railway-ready** — includes `railway.toml` for one-command deployment

---

## Commands

| Command | Description |
|---|---|
| `/start` | Introduction and quick-start guide |
| `/summary` | Monthly overview: income, spending, savings, net balance, and category breakdown |
| `/today` | Everything logged today plus total spent |
| `/top5` | Top 5 biggest expenses this month |
| `/help` | Full usage guide |

You can also just type a message — no command needed to log an entry.

---

## Logging Format

The bot understands flexible natural language:

```
150 lunch                     → Expense · Food · 150 ETB
500 rent                      → Expense · Rent · 500 ETB
income 8000 salary            → Income · 8,000 ETB
saved 1000                    → Savings · 1,000 ETB
spent 200 on transport        → Expense · Transport · 200 ETB
300 medicine                  → Expense · Health · 300 ETB
```

Words like `spent`, `on`, `for`, `etb`, and `birr` are ignored so you can write naturally.

---

## Google Sheets Structure

Each month gets a sheet with these columns:

| Date | Time | Type | Amount (ETB) | Category | Note |
|---|---|---|---|---|---|
| 2026-04-24 | 14:30 | Expense | 150 | Food | Lunch |

The `📊 Dashboard` sheet is always kept up to date with:
- Monthly income / spent / saved / net balance
- Average daily expense and today's spending
- Spending by category (with percentage bars)
- Top 5 biggest expenses
- Savings rate as a percentage of income

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/KenbonTN/expense-tracker-bot.git
cd expense-tracker-bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Run `/newbot` and follow the prompts
3. Copy the token you receive

### 4. Set up Google Sheets + Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a new project
2. Enable the **Google Sheets API** and **Google Drive API**
3. Create a **Service Account** and download the JSON credentials file
4. Create a new Google Spreadsheet and copy its ID from the URL:
   `https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit`
5. Share the spreadsheet with the service account email (give it Editor access)

### 5. Get your Telegram chat ID

Message [@userinfobot](https://t.me/userinfobot) on Telegram — it will reply with your user ID.

### 6. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
TELEGRAM_TOKEN=your_telegram_bot_token_here
SPREADSHEET_ID=your_google_spreadsheet_id_here
GOOGLE_CREDENTIALS_FILE=your_credentials_file.json
MY_CHAT_ID=your_telegram_user_id_here
```

### 7. Run the bot

```bash
python bot.py
```

---

## Deploying to Railway

This project includes a `railway.toml` file for easy deployment on [Railway](https://railway.app).

1. Push the repo to GitHub
2. Create a new Railway project and connect your repo
3. Add all environment variables from `.env` in the Railway dashboard
4. Upload your Google credentials JSON as a file and set `GOOGLE_CREDENTIALS_FILE` to its path
5. Deploy — Railway will automatically restart the bot on failure

---

## Configuration

You can customize the following directly in `bot.py`:

| Variable | Default | Description |
|---|---|---|
| `TIMEZONE` | `Africa/Addis_Ababa` | Your local timezone (any `pytz` timezone string) |
| `ALERT_THRESHOLDS` | `[250, 500, 700, 1000]` | Daily spending levels that trigger alerts (in ETB) |
| `EXPENSE_CATEGORIES` | see code | Keywords mapped to each spending category |

---

## Project Structure

```
expense-tracker-bot/
├── bot.py               # Main bot logic
├── requirements.txt     # Python dependencies
├── railway.toml         # Railway deployment config
├── .env.example         # Environment variable template
└── .gitignore
```

---

## Requirements

- Python 3.10+
- A Telegram bot token (from @BotFather)
- A Google Cloud service account with Sheets + Drive API access
- A Google Spreadsheet shared with the service account
