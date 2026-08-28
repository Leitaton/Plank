"""
Plank — Central Configuration
All bot settings, plan specs, and tunables live here.
Owners can also hot-edit values via /admin commands.
"""

import json
import os

from dotenv import load_dotenv

load_dotenv()

# ── Core ──────────────────────────────────────────────
BOT_TOKEN = "8863097709:AAEjlcMOhvHE3qWgupS_zhuQ23nNNAe8Rno"
CHECKER_API_URL = "https://api.iplank.pro"

# ── Redis (Upstash) ───────────────────────────────────
# Set REDIS_URL in the environment / .env, e.g.
#   rediss://default:<password>@<host>.upstash.io:6379
# Leave unset to disable Redis (bot falls back to in-memory caches).
REDIS_URL = os.getenv("REDIS_URL", "rediss://default:gQAAAAAAAaw7AAIgcDFkNDljMjQ2MzZjZDM0MGZlOTVkY2UyN2ZlMDU0OWI3YQ@divine-lemur-109627.upstash.io:6379")

# Default TTL (seconds) for cached BIN lookups
BIN_CACHE_TTL = int(os.getenv("BIN_CACHE_TTL", "86400"))
MAX_PRICE = 8.00  # Maximum acceptable product price for Shopify checks (in USD)
MAX_SITE_TIME = 5.0 # Maximum time in seconds for a site to respond before being marked as slow
MAX_CONCURRENT_API_REQUESTS = 100  # Max concurrent requests to checker API
DATABASE_PATH = "plankbot.db"

# ── Telegram MTProto (for /scr channel scraping) ─────
TELEGRAM_API_ID = 0
TELEGRAM_API_HASH = ""

# ── Scraper limits ────────────────────────────────────
SCRAPE_LIMIT_DEFAULT = 5000

# ── Community ─────────────────────────────────────────
REQUIRED_CHAT_ID = -1003979682778
REQUIRED_CHANNEL_ID = -1003999755491

CHAT_INVITE_LINK = "https://t.me/+FmiZjpHNXPw2MzI1"
CHANNEL_INVITE_LINK = "https://t.me/+NvlVq70JhbhjMDI1"

# ── Hit log channels ──────────────────────────────────
HIT_PUBLIC_CHAT_ID = -1003979682778
HIT_PRIVATE_CHANNEL_ID = -5154377985

# ── Owners (Telegram user IDs) ───────────────────────
OWNER_IDS = [7985375134]

# ── Plans ─────────────────────────────────────────────
PLANS = {
    "dirt": {
        "display": "Dirt",
        "emoji": "🟤",
        "price": "Free",
        "credits": 500,
        "workers": 10,
        "cooldown": 2,
        "mass_limit": 100,
        "support": "community",
        "daily_bonus": 25,
    },

    "cobblestone": {
        "display": "Iron",
        "emoji": "⚡️",
        "price": "$5/week",
        "credits": 5000,
        "workers": 20,
        "cooldown": 0.5,
        "mass_limit": 500,
        "support": "standard",
        "daily_bonus": 100,
    },

    "diamond": {
        "display": "Diamond",
        "emoji": "⭐️",
        "price": "$15/mo",
        "credits": 50000,
        "workers": 40,
        "cooldown": 0,
        "mass_limit": 2000,
        "support": "priority",
        "daily_bonus": 500,
    },

    "bedrock": {
        "display": "Netherite",
        "emoji": "💎",
        "price": "$30/mo",
        "credits": 100000,
        "workers": 80,
        "cooldown": 0,
        "mass_limit": 5000,
        "support": "priority",
        "daily_bonus": 1000,
    },
}

DEFAULT_PLAN = "dirt"

# ── Redeem code prefix ────────────────────────────────
REDEEM_PREFIX = "PLANK"

# ── Rate limits ───────────────────────────────────────
DAILY_COOLDOWN_HOURS = 24

# ── Proxy pool (managed at runtime via /proxy) ───────
PROXY_FILE = "proxies.txt"

# ── Shopify site list for scraping ────────────────────
SHOPIFY_SITES_FILE = "sites.txt"

# ── UI / Aesthetics ──────────────────────────────────
BRAND_NAME = "Plank"
PROGRESS_FILLED = "🌸"
PROGRESS_EMPTY = "💮"
PROGRESS_BAR_LENGTH = 10

# ── BIN lookup API ────────────────────────────────────
BIN_API_URL = "https://bins.antipublic.cc/bins/{bin}"

# ── Custom contact for custom plans ──────────────────
CUSTOM_PLAN_CONTACT = "@iceyy69"

# ── Scraper card regex pattern ───────────────────────
CARD_PATTERN = (
    r'\b(\d{13,19})\s*[|/:\s]\s*'
    r'(\d{1,2})\s*[|/:\s]\s*'
    r'(\d{2,4})\s*[|/:\s]\s*'
    r'(\d{3,4})\b'
)

# ── Owner Debug Mode ──────────────────────────────────
OWNER_DEBUG_MODE = {}

