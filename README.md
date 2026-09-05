# 🏛️ ArchiScrapping

**Architect Job Aggregator for Germany** — Scrapes and deduplicates architect job postings from LinkedIn, Indeed, Glassdoor, Google Jobs, and ZipRecruiter into a single premium dashboard.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green) ![Deploy](https://img.shields.io/badge/deploy-Railway-purple)

## Features

- 🔍 **Multi-board scraping** — LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter
- 🔄 **Smart deduplication** — Fuzzy matching detects same job across boards, shows "Also on: LinkedIn, Indeed" badges
- 🏙️ **City-level detail** — Shows which German city each job is in
- 💰 **Salary display** — Shows salary ranges when provided
- 📅 **Date tracking** — When it was posted and when it was first seen
- 📊 **Dashboard with charts** — Jobs by city, by source, with live stats
- 🔎 **Filtering** — Search, city, source, job type, salary, sorting
- ⏰ **Auto-scrape** — Periodic scraping every 6 hours (configurable)
- 🔔 **Instant Telegram alerts** — Real-time notifications to your Telegram chat or channel whenever a new offer appears
- 🚀 **Railway ready** — One-click deploy with Dockerfile

## Telegram Notifications Setup

Receive instant notifications directly on your phone/desktop whenever a new architect position is found:

1. **Create a Telegram Bot**:
   - Open Telegram and message [@BotFather](https://t.me/BotFather)
   - Send `/newbot` and follow the prompts to choose a name and username
   - Copy the generated **HTTP API Bot Token** (e.g. `123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`)

2. **Get Your Telegram Chat ID**:
   - Start a chat with your new bot and send any message (e.g. "hi")
   - Open Telegram and message [@userinfobot](https://t.me/userinfobot) to get your numeric **Id** (e.g. `123456789`)
   - *(Alternative for channels/groups)*: Add the bot as an administrator to your channel and use the channel ID or chat ID.

3. **Configure the App**:
   - In `.env` (locally) or Railway Dashboard (production):
     ```bash
     TELEGRAM_BOT_TOKEN="your_bot_token_here"
     TELEGRAM_CHAT_ID="your_chat_id_here"
     ```
   - Click the **Telegram Alert** button in the dashboard or send `POST /api/telegram/test` to test your connection!

## Quick Start

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your settings (optional — defaults work fine)
```

### 3. Run

```bash
python main.py
# or
uvicorn main:app --reload --port 8000
```

Visit **http://localhost:8000** 🎉

## Deploy to Railway

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) and click **New Project** → **Deploy from GitHub repo**
3. Select your `ArchiScrapping` repository
4. Railway will automatically detect the `Dockerfile` and `railway.toml`
5. Set environment variables in the Railway project dashboard (**Variables** tab):
   - `TELEGRAM_BOT_TOKEN` — Your Telegram Bot Token from @BotFather
   - `TELEGRAM_CHAT_ID` — Your Telegram Chat ID from @userinfobot
   - `SCRAPE_INTERVAL_HOURS` — Hours between automatic scraping runs (default: `6`)
   - `RESULTS_PER_SITE` — Max results per site per search (default: `50`)
6. **Data Persistence** *(Recommended)*:
   - In your Railway service settings, go to **Volumes** → **Add Volume**
   - Mount path: `/data`
   - The app will automatically store SQLite data at `/data/archiscrapping.db` so jobs persist across deployments!

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./archiscrapping.db` | Database connection string (auto-detects `/data` volume) |
| `TELEGRAM_BOT_TOKEN` | _(empty)_ | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | _(empty)_ | Telegram recipient chat ID |
| `TELEGRAM_ENABLED` | `true` | Enable or disable Telegram notifications |
| `SCRAPE_INTERVAL_HOURS` | `6` | Hours between automatic scrapes |
| `RESULTS_PER_SITE` | `50` | Max results per site per search |
| `SEARCH_TERMS` | `Architekt,Architect,...` | Comma-separated search terms |
| `PROXY_LIST` | _(empty)_ | Comma-separated proxies |
| `PORT` | `8000` | Server port (set by Railway) |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Dashboard UI |
| `GET` | `/api/jobs` | List jobs (with filters & pagination) |
| `GET` | `/api/stats` | Aggregated statistics |
| `GET` | `/api/filters` | Available filter options |
| `POST` | `/api/scrape` | Trigger manual scrape |
| `GET` | `/api/scrape/status` | Check latest scrape status |

## Tech Stack

- **Backend**: Python 3.11 + FastAPI + SQLAlchemy + APScheduler
- **Scraping**: python-jobspy (multi-board aggregation)
- **Deduplication**: thefuzz (fuzzy string matching)
- **Frontend**: Vanilla HTML/CSS/JS + Chart.js
- **Deployment**: Docker + Railway
