"""
Plank — Shared helpers.
"""

import re
import time
import random
import string
from datetime import datetime, timezone

import aiohttp

from config import (
    PLANS,
    OWNER_IDS,
    REQUIRED_CHAT_ID,
    REQUIRED_CHANNEL_ID,
    PROGRESS_BAR_LENGTH,
)
from utils.emojis import E_PROGRESS_FILLED, E_PROGRESS_EMPTY


def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


def get_plan_info(plan_name: str) -> dict:
    return PLANS.get(plan_name, PLANS["dirt"])


def credits_display(credits: int) -> str:
    if credits == -1:
        return "∞ unlimited"
    return f"{credits:,}"


def progress_bar(current: int, total: int) -> str:
    if total <= 0:
        return str(E_PROGRESS_EMPTY) * PROGRESS_BAR_LENGTH
    ratio = min(current / total, 1.0)
    filled = int(ratio * PROGRESS_BAR_LENGTH)
    empty = PROGRESS_BAR_LENGTH - filled
    return str(E_PROGRESS_FILLED) * filled + str(E_PROGRESS_EMPTY) * empty


def progress_pct(current: int, total: int) -> int:
    if total <= 0:
        return 0
    return min(int((current / total) * 100), 100)


def timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%I:%M %p")


def generate_redeem_code(plan: str) -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"PLANK-{plan.upper()}-{suffix}"


def parse_duration(text: str) -> int:
    """Parse '7d', '30d', '1w', '1m' into seconds."""
    text = text.strip().lower()
    if text.endswith("d"):
        return int(text[:-1]) * 86400
    if text.endswith("w"):
        return int(text[:-1]) * 604800
    if text.endswith("m"):
        return int(text[:-1]) * 2592000
    if text.endswith("h"):
        return int(text[:-1]) * 3600
    return int(text) * 86400


_CARD_EXTRACT_RE = re.compile(
    r'(\d{13,19})\s*[|/:\s]\s*(\d{1,2})\s*[|/:\s]\s*(\d{2,4})\s*[|/:\s]\s*(\d{3,4})'
)


def parse_cards(text: str, filter_expired: bool = True) -> list[str]:
    """Parse cards from text in ANY format. Auto-detects CC|MM|YY|CVV from lines
    containing card numbers. Filters invalid and expired cards.
    Handles formats like:
      4111111111111111|12|27|123
      APR 4111111111111111|12|27|123 | $4.28 | AUTHENTICATION_REQUIRED
      4111111111111111:12:27:123
      4111111111111111/12/27/123
    """
    from datetime import datetime, timezone

    cards = []
    seen = set()
    now = datetime.now(timezone.utc)
    current_month = now.month
    current_year = now.year % 100  # 2-digit year

    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        for match in _CARD_EXTRACT_RE.finditer(line):
            cc = match.group(1)
            mm = match.group(2).zfill(2)
            yy = match.group(3)
            cvv = match.group(4)

            # Normalize year to 2-digit
            if len(yy) == 4:
                yy = yy[2:]

            # Validate CC
            if not cc.isdigit() or len(cc) < 13:
                continue

            # Validate month
            try:
                m = int(mm)
                if m < 1 or m > 12:
                    continue
            except ValueError:
                continue

            # Validate CVV
            if not cvv.isdigit() or len(cvv) < 3:
                continue

            # Filter expired cards
            if filter_expired:
                try:
                    y = int(yy)
                    if y < current_year or (y == current_year and int(mm) < current_month):
                        continue
                except ValueError:
                    continue

            card = f"{cc}|{mm}|{yy}|{cvv}"
            if card not in seen:
                seen.add(card)
                cards.append(card)

    return cards


def mask_card(card: str) -> str:
    """Mask middle digits of a card for public display."""
    parts = card.split("|")
    if len(parts) != 4:
        return card
    cc = parts[0]
    if len(cc) > 8:
        masked = cc[:6] + "x" * (len(cc) - 10) + cc[-4:]
    else:
        masked = cc
    return f"{masked}|{parts[1]}|{parts[2]}|{parts[3]}"


_membership_cache: dict[int, tuple[bool, bool, float]] = {}
_MEMBERSHIP_TTL_SUCCESS = 600  # cache success for 10 minutes
_MEMBERSHIP_TTL_FAILURE = 30   # cache failure for 30 seconds


async def check_membership(bot, user_id: int) -> tuple[bool, bool]:
    """Check if user is member of required chat and channel (parallel, cached)."""
    import asyncio

    # Owners always pass
    if user_id in OWNER_IDS:
        return True, True

    now = time.time()
    cached = _membership_cache.get(user_id)
    if cached:
        in_chat, in_channel, ts = cached
        passed = in_chat and in_channel
        ttl = _MEMBERSHIP_TTL_SUCCESS if passed else _MEMBERSHIP_TTL_FAILURE
        if now - ts < ttl:
            return in_chat, in_channel

    _MEMBER_STATUSES = ("member", "administrator", "creator", "restricted")

    async def _check(chat_id):
        if not chat_id:
            return True
        for attempt in range(2):
            try:
                member = await bot.get_chat_member(chat_id, user_id)
                if member.status == "restricted":
                    try:
                        return member.is_member
                    except AttributeError:
                        return True
                return member.status in _MEMBER_STATUSES
            except Exception:
                if attempt == 0:
                    await asyncio.sleep(0.3)
                    continue
                return False
        return False

    in_chat, in_channel = await asyncio.gather(
        _check(REQUIRED_CHAT_ID),
        _check(REQUIRED_CHANNEL_ID),
    )

    _membership_cache[user_id] = (in_chat, in_channel, now)
    return in_chat, in_channel


_IP_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)

_HOST_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,}$"
)


def validate_proxy(proxy: str) -> bool:
    """Validate proxy format: host:port:user:pass (4+ parts separated by colons).
    Checks IP/hostname format and port range.
    """
    parts = proxy.strip().split(":")
    if len(parts) < 4:
        return False
    host = parts[0]
    port = parts[1]
    if not host or not port:
        return False
    if not (_IP_RE.match(host) or _HOST_RE.match(host)):
        return False
    try:
        p = int(port)
        if p < 1 or p > 65535:
            return False
    except ValueError:
        return False
    user = parts[2]
    password = ":".join(parts[3:])
    if not user or not password:
        return False
    return True


_proxy_check_timeout = aiohttp.ClientTimeout(total=8)


async def check_proxy_alive(proxy_str: str, timeout_sec: int = 8) -> bool:
    """Test if a proxy is actually reachable by hitting httpbin."""
    try:
        proxy_url = proxy_to_url(proxy_str)
        timeout = _proxy_check_timeout if timeout_sec == 8 else aiohttp.ClientTimeout(total=timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://httpbin.org/ip",
                proxy=proxy_url,
            ) as resp:
                return resp.status == 200
    except Exception:
        return False


def proxy_to_url(proxy: str) -> str:
    """Convert host:port:user:pass to http://user:pass@host:port."""
    parts = proxy.strip().split(":")
    host = parts[0]
    port = parts[1]
    user = parts[2]
    password = ":".join(parts[3:])
    return f"http://{user}:{password}@{host}:{port}"


def time_since(ts: float) -> str:
    diff = time.time() - ts
    if diff < 3600:
        return f"{int(diff / 60)}m ago"
    if diff < 86400:
        return f"{int(diff / 3600)}h ago"
    return f"{int(diff / 86400)}d ago"


_bin_session: aiohttp.ClientSession | None = None
_bin_timeout = aiohttp.ClientTimeout(total=6)
_bin_cache: dict[str, dict] = {}


async def lookup_bin(bin_number: str) -> dict:
    """Lookup BIN info with caching and shared session."""
    global _bin_session
    from config import BIN_API_URL

    bin6 = bin_number[:6]
    if bin6 in _bin_cache:
        return _bin_cache[bin6]

    try:
        if _bin_session is None or _bin_session.closed:
            _bin_session = aiohttp.ClientSession(
                timeout=_bin_timeout,
                connector=aiohttp.TCPConnector(limit=20, keepalive_timeout=30),
            )
        async with _bin_session.get(
            BIN_API_URL.format(bin=bin6)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                result = {
                    "scheme": (data.get("brand") or "N/A").upper(),
                    "type": (data.get("type") or "N/A").upper(),
                    "brand": (data.get("level") or "N/A").upper(),
                    "bank": (data.get("bank") or "N/A").upper(),
                    "country": (data.get("country_name") or data.get("country") or "N/A").upper(),
                    "country_emoji": data.get("country_flag") or "",
                }
                _bin_cache[bin6] = result
                return result
    except Exception:
        pass
    return {
        "scheme": "N/A", "type": "N/A", "brand": "N/A",
        "bank": "N/A", "country": "N/A", "country_emoji": "",
    }

