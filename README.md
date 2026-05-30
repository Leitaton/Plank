# Plank — Advanced Telegram Bot

Premium Telegram checker bot with credit system, Shopify gate via external API, utility tools, and full admin panel. Built to handle **400–500+ concurrent members**.

---

## Features

### Plans & Credits
| Plan | Price | Workers | Credits | Cooldown | Mass Limit |
|------|-------|---------|---------|----------|------------|
| 🟤 Dirt | Free | 10w | 500 | 5s | 100 |
| ⚡️ Cobblestone | $5/week | 20w | 5,000 | 2s | 500 |
| ⭐️ Diamond | $15/mo | 40w | ∞ | 0s | 2,000 |
| 💎 Bedrock | $30/mo | 80w | ∞ | 0s | 5,000 |

### Gates (Checker Suite)
- `/sh` — Single Shopify check (via external API)
- `/msh` — Mass Shopify (inline cards or `.txt` upload)

### Tools (Utility Suite)
- `/vbv` / `/mvbv` — 3DS/VBV single & mass check
- `/bin` — BIN lookup
- `/proxy list|add|remove|test` — Proxy manager
- `/split` — Split combo file into `CC|MM|YY|CVV`
- `/genad` — Generate address by country
- `/scr` — Scrape cards from public channels

### Credit Commands
- `/daily` — Claim daily credit bonus
- `/redeem` — Redeem promo code (`PLANK-PLAN-XXXXXXXX`)
- `/balance` — Check credits & plan info
- `/plans` — View available plans

### Admin Panel (Owner-only)
- `/admin` — Interactive admin menu
- `/genplan {plan} {duration} {qty}` — Generate redeem codes
- `/setplan {user_id} {plan} {duration}` — Set user plan
- `/addcredits {user_id} {amount}` — Add credits
- `/ban` / `/unban` — Ban/unban users
- `/userinfo {user_id}` — View user details
- `/stats` — Bot statistics
- `/broadcast {message}` — Message all users
- `/allusers` — List all registered users
- `/site list|add|check` — Manage Shopify sites
- `/sitechk` — Reply to .txt with Shopify sites to validate via API
- `/siteadd` — Reply to valid_sites.txt to add validated sites

### Mass Checking UI
Live-updating progress display with:
- Progress bar & percentage
- Worker count & queue size
- Hit counts (Charged / Approved / Dead / Error)
- Recent hits section
- Interactive buttons for filtering results & stopping

### Hit Notifications
- **Public chat**: Gate, amount, username (no card info)
- **Private channel**: Gate, amount, username + full card details
- **DM**: Detailed charge notification with BIN info

### Membership Gate
Users must join both the group and channel before using any commands.

---

## Setup

### 1. Clone & install
```bash
git clone https://github.com/IceyyDev/PlankBot.git
cd PlankBot
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env with your values
```

### 3. Start external checker API
The bot requires an external checker API. Set the URL via `CHECKER_API_URL` env var.

The API must provide:
- `GET /shopify?site={site}&cc={cc}|{mm}|{yy}|{cvv}&proxy={proxy}`
- `GET /check?site={site}`

### 4. Run the bot
```bash
python bot.py
```

---

## Project Structure
```
PlankBot/
├── bot.py              # Main bot entry point
├── config.py           # All configuration & plan specs
├── database.py         # SQLite database layer
├── handlers/
│   ├── start.py        # /start, /help, /plans, join checks
│   ├── credits.py      # /daily, /balance, /redeem
│   ├── gates.py        # /sh, /msh + mass UI (external API)
│   ├── tools.py        # /vbv, /mvbv, /bin, /proxy, /split, /genad, /scr
│   └── admin.py        # /admin, /genplan, /sitechk, /siteadd
├── utils/
│   ├── emojis.py       # Unicode bold text & emoji helpers
│   ├── helpers.py      # Shared utility functions
│   ├── keyboards.py    # Inline keyboard builders
│   └── checkers.py     # External API checker wrappers
├── emojis.json         # Customisable emoji configuration
├── requirements.txt
├── .env.example
└── README.md
```

---

## Configuration Reference

All settings in `config.py` can be overridden via environment variables:

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `CHECKER_API_URL` | External checker API URL (e.g. `http://ip:port`) |
| `REQUIRED_CHAT_ID` | Group ID users must join |
| `REQUIRED_CHANNEL_ID` | Channel ID users must join |
| `OWNER_IDS` | JSON array of owner Telegram user IDs |
| `HIT_PUBLIC_CHAT_ID` | Public hit notification chat |
| `HIT_PRIVATE_CHANNEL_ID` | Private hit notification channel |

---

## Redeem Codes

Format: `PLANK-{PLAN}-{RANDOM8}`

Generate with: `/genplan diamond 30d 10` (generates 10 Diamond codes, each valid 30 days)

---

*Built for hitters · more gates in pipeline*
