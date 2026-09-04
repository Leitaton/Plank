"""
Plank — Utility tool handlers:
/vbv, /mvbv, /bin, /proxy, /split, /genad, /scr
"""

import asyncio
import random
import re
import uuid
import time
import logging
from io import BytesIO

import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

from config import (
    BRAND_NAME, BIN_API_URL, PLANS,
    SCRAPE_LIMIT_DEFAULT, CARD_PATTERN,
)
from database import (
    ensure_user, get_user, deduct_credits,
    add_proxy, remove_proxy, get_user_proxies, get_all_proxies, set_proxy_status,
    run_in_db,
)
from utils.emojis import (
    section, bold, separator,
    E_LOCK, E_BIN, E_CHAIN, E_INFO, E_BOLT, E_CHECK, E_CROSS,
    E_ARROW, E_ERROR, E_EARTH, E_CHART, E_MONEY, E_PC, E_FIRE,
    E_HEART, E_STAR, E_CLOCK, E_WARN, E_DIAMOND, E_SECTION_OPEN, E_SECTION_CLOSE,
)
from utils.helpers import (
    get_plan_info, parse_cards, credits_display,
    progress_bar, progress_pct, timestamp_now,
    validate_proxy, proxy_to_url, check_proxy_alive, is_owner,
    lookup_bin,
)
from utils.keyboards import mass_keyboard
from utils.checkers import check_vbv
from handlers.start import membership_guard

logger = logging.getLogger("Plank.tools")


# ── /vbv  — single VBV check ─────────────────────────

async def vbv_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    user = update.effective_user
    db_user = await run_in_db(ensure_user, user.id, user.username or "")

    if not context.args:
        await update.message.reply_text(
            f"{E_LOCK} <b>3D Secure VBV</b>\n\n{E_HEART} /vbv CC|MM|YY|CVV\n"
        )
        return

    card_str = context.args[0].strip()
    parts = card_str.split("|")
    if len(parts) != 4:
        await update.message.reply_text(f"{E_BIN} format: /vbv CC|MM|YY|CVV")
        return

    if not await run_in_db(deduct_credits, user.id, 1):
        await update.message.reply_text(f"{E_CROSS} no credits · /daily")
        return

    msg = await update.message.reply_text(f"{E_LOCK} checking <code>{card_str}</code>...")

    user_proxies = await run_in_db(get_user_proxies, user.id, True)
    if not user_proxies:
        user_proxies = await run_in_db(get_user_proxies, user.id, False)
    proxy = proxy_to_url(random.choice(user_proxies)) if user_proxies else None
    is_priority = db_user.get("plan", "dirt") in ("diamond", "bedrock")

    result = await check_vbv(parts[0], parts[1], parts[2], parts[3], proxy=proxy, is_priority=is_priority)

    vbv_status = result.get("VBV", "Unknown")
    bin_num = parts[0][:6]
    bin_info = await lookup_bin(bin_num)

    if vbv_status == "Yes":
        req = f"{E_CHECK}  " + bold("required")
        ease = bold("harder to charge")
    else:
        req = f"{E_CROSS}  " + bold("not required")
        ease = bold("easy to charge")

    text = (
        f"{bold(BRAND_NAME)}:\n"
        f"{section(E_LOCK, 'VBV / 3DS')}  —  {bin_num}\n"
        f"{section(E_LOCK, 'Verdict')}\n"
        f"▸  type · {bold('VBV / 3DS')}\n"
        f"▸  3ds  · {req}\n"
        f"▸  ease · {ease}\n"
        f"{section(E_MONEY, 'Card')}\n"
        f"▸  brand · {bold(bin_info['scheme'])}\n"
        f"▸  type  · {bold(bin_info['type'])}\n"
        f"▸  level · {bold(bin_info['brand'])}\n"
        f"{section(E_CLOCK, 'Issuer')}\n"
        f"▸  bank · {bold(bin_info['bank'])}\n"
        f"▸  ctry · {bold(bin_info['country'])} {bin_info['country_emoji']}\n"
    )

    await msg.edit_text(text)


# ── /mvbv  — mass VBV check ──────────────────────────

async def mvbv_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    user = update.effective_user
    db_user = await run_in_db(ensure_user, user.id, user.username or "")
    plan_info = get_plan_info(db_user["plan"])
    is_priority = db_user.get("plan", "dirt") in ("diamond", "bedrock")

    cards = await _extract_cards_for_tools(update, context)
    if not cards:
        await update.message.reply_text(
            f"{E_LOCK} <b>Mass VBV</b>\n\n{E_HEART} /mvbv CC|MM|YY|CVV or reply .txt\n"
        )
        return

    mass_limit = plan_info["mass_limit"]
    if not is_owner(user.id) and len(cards) > mass_limit:
        skipped_cards = cards[mass_limit:]
        cards = cards[:mass_limit]
        skipped_text = "\n".join(skipped_cards)
        buf = BytesIO(skipped_text.encode("utf-8"))
        buf.name = "skipped.txt"
        try:
            await update.message.reply_document(
                buf,
                caption=f"{E_WARN} Limit exceeded! Checked first {mass_limit} cards. Skipped remaining {len(skipped_cards)} cards."
            )
        except Exception:
            pass

    if not await run_in_db(deduct_credits, user.id, len(cards)):
        await update.message.reply_text(f"{E_CROSS} no credits · /daily")
        return

    user_proxies = await run_in_db(get_user_proxies, user.id, True)
    if not user_proxies:
        user_proxies = await run_in_db(get_user_proxies, user.id, False)

    session_id = uuid.uuid4().hex[:8]
    vbv_cards = []
    non_vbv = []
    errors = []
    processed = 0

    msg = await update.message.reply_text(f"{E_LOCK} checking {len(cards)} cards...")

    cooldown = plan_info["cooldown"]
    workers = plan_info["workers"]

    queue = asyncio.Queue()
    for c in cards:
        await queue.put(c)

    async def worker():
        nonlocal processed
        while not queue.empty():
            try:
                card = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            parts = card.split("|")
            if len(parts) != 4:
                errors.append(card)
                processed += 1
                queue.task_done()
                continue

            proxy = proxy_to_url(random.choice(user_proxies)) if user_proxies else None
            result = await check_vbv(parts[0], parts[1], parts[2], parts[3], proxy=proxy, is_priority=is_priority)
            if result.get("VBV") == "Yes":
                vbv_cards.append(card)
            else:
                non_vbv.append(card)
            processed += 1
            queue.task_done()

            if cooldown > 0 and not queue.empty():
                await asyncio.sleep(cooldown)

    tasks = [asyncio.create_task(worker()) for _ in range(workers)]
    await asyncio.gather(*tasks)

    await msg.edit_text(
        f"{E_LOCK} <b>VBV Check Complete</b>\n\n"
        f"{E_HEART} 3DS VBV: <b>{len(vbv_cards)}</b>\n"
        f"{E_HEART} Non-3DS: <b>{len(non_vbv)}</b>\n"
        f"{E_HEART} Errors: <b>{len(errors)}</b>\n"
    )


# ── /bin  — BIN lookup ────────────────────────────────

async def bin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            f"{section(E_BIN, 'BIN')}\n\n╰ /bin 457173\n"
        )
        return

    bin_number = context.args[0].strip()[:8]
    if not bin_number.isdigit() or len(bin_number) < 6:
        await update.message.reply_text(f"{E_SECTION_OPEN} {E_BOLT} {E_SECTION_CLOSE} need 6+ digits")
        return

    msg = await update.message.reply_text(f"{E_BIN} looking up <code>{bin_number}</code>...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                BIN_API_URL.format(bin=bin_number[:6]),
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    brand = (data.get("brand") or "N/A").upper()
                    card_type = (data.get("type") or "N/A").upper()
                    level = (data.get("level") or "N/A").upper()
                    country_name = (data.get("country_name") or data.get("country") or "N/A").upper()
                    country_emoji = data.get("country_flag") or ""
                    bank_name = (data.get("bank") or "N/A").upper()

                    await msg.edit_text(
                        f"{E_BIN} <b>BIN</b> · <code>{bin_number}</code>\n\n"
                        f"{E_HEART} brand: {brand}\n"
                        f"{E_HEART} type: {card_type} · {level}\n"
                        f"{E_HEART} bank: {bank_name}\n"
                        f"{E_HEART} ctry: {country_emoji} {country_name}\n"
                    )
                else:
                    await msg.edit_text(f"{E_CROSS} BIN not found")
    except Exception:
        await msg.edit_text(f"{E_ERROR} lookup failed")


# ── /proxy  — proxy management ────────────────────────

async def proxy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    def _mask_proxy(proxy: str) -> str:
        parts = proxy.split(":")
        if len(parts) == 4:
            host, port, user, password = parts
            user_masked = user[0] + "***" if len(user) > 0 else "***"
            pass_masked = password[0] + "***" if len(password) > 0 else "***"
            return f"{host}:{port}:{user_masked}:{pass_masked}"
        return proxy

    if not context.args:
        await update.message.reply_text(
            f"{section(E_CHAIN, 'Proxy')}\n\n"
            f"╰ /proxy list · add · remove · test · clear\n"
            f"╰ format: ip:port:user:pass\n"
        )
        return

    user_id = update.effective_user.id
    sub = context.args[0].lower()

    if sub == "list":
        proxies = await run_in_db(get_user_proxies, user_id, False)
        if not proxies:
            await update.message.reply_text(
                f"{section(E_CHAIN, 'no proxies')} · /proxy add\n"
            )
            return
        text = f"{section(E_CHAIN, 'Proxies', f' · {len(proxies)}')}\n\n"
        for p in proxies[:50]:
            text += f"╰ {_mask_proxy(p)}\n"
        await update.message.reply_text(text)

    elif sub == "add" and (len(context.args) > 1 or (update.message.reply_to_message and update.message.reply_to_message.document)):
        proxy_list = []
        reply = update.message.reply_to_message
        if reply and reply.document:
            try:
                file = await reply.document.get_file()
                data = await file.download_as_bytearray()
                text = data.decode("utf-8", errors="ignore")
                proxy_list = [l.strip() for l in text.splitlines() if l.strip()]
            except Exception:
                await update.message.reply_text(f"{E_CROSS} Failed to read proxy file.")
                return
        else:
            proxy_list = [p.strip() for p in context.args[1:] if p.strip()]

        if not proxy_list:
            await update.message.reply_text(
                f"{E_CROSS} No proxies provided.\n"
                f"   {E_ARROW} /proxy add host:port:user:pass\n"
                f"   {E_ARROW} Or reply to a .txt file with /proxy add"
            )
            return

        valid_proxies = []
        invalid = []
        for proxy_str in proxy_list:
            if validate_proxy(proxy_str):
                valid_proxies.append(proxy_str)
            else:
                invalid.append(proxy_str)

        if not valid_proxies:
            await update.message.reply_text(
                f"{E_CROSS} All proxies have invalid format.\n\n"
                f"   {E_ARROW} Required: host:port:user:pass\n"
                f"   {E_ARROW} host must be a valid IP or domain\n"
                f"   {E_ARROW} Example: 1.2.3.4:8080:myuser:mypass"
            )
            return

        msg = await update.message.reply_text(
            f"{E_CHAIN} Testing {len(valid_proxies)} proxies..."
        )

        alive_count = 0
        dead_count = 0
        semaphore = asyncio.Semaphore(10)

        async def test_and_add(p: str):
            nonlocal alive_count, dead_count
            async with semaphore:
                alive = await check_proxy_alive(p, timeout_sec=10)
                if alive:
                    await run_in_db(add_proxy, p, user_id)
                    alive_count += 1
                else:
                    dead_count += 1

        tasks = [asyncio.create_task(test_and_add(p)) for p in valid_proxies]
        await asyncio.gather(*tasks)

        result_text = (
            f"{section(E_CHAIN, 'Added')}\n\n"
            f"╰ tested {bold(str(len(valid_proxies)))} · "
            f"alive {bold(str(alive_count))} · "
            f"dead {bold(str(dead_count))}\n"
        )
        if invalid:
            result_text += f"╰ invalid {bold(str(len(invalid)))}\n"

        await msg.edit_text(result_text)

    elif sub == "remove" and len(context.args) > 1:
        proxy_str = context.args[1].strip()
        await run_in_db(remove_proxy, proxy_str, user_id)
        await update.message.reply_text(f"{E_CHECK} Proxy removed: {proxy_str}")

    elif sub == "clear":
        proxies = await run_in_db(get_user_proxies, user_id, False)
        if not proxies:
            await update.message.reply_text(
                f"{section(E_CHAIN, 'no proxies to clear')}\n"
            )
            return

        for p in proxies:
            await run_in_db(remove_proxy, p, user_id)

        await update.message.reply_text(
            f"{section(E_CHECK, 'Cleared All Proxies')}\n\n"
            f"   {E_ARROW} removed {bold(str(len(proxies)))} proxies"
        )

    elif sub == "test":
        proxies = await run_in_db(get_user_proxies, user_id, False)
        if not proxies:
            await update.message.reply_text(
                f"{section(E_CHAIN, 'no proxies')} · /proxy add\n"
            )
            return

        msg = await update.message.reply_text(
            f"{E_SECTION_OPEN} {E_CHAIN} {E_SECTION_CLOSE} testing {len(proxies)} proxies..."
        )

        semaphore = asyncio.Semaphore(10)
        alive_proxies = []
        dead_proxies = []

        async def test_one(proxy_str: str):
            async with semaphore:
                alive = await check_proxy_alive(proxy_str, timeout_sec=8)
                if alive:
                    alive_proxies.append(proxy_str)
                else:
                    dead_proxies.append(proxy_str)

        tasks = [asyncio.create_task(test_one(p)) for p in proxies]
        await asyncio.gather(*tasks)

        # ── REMOVE DEAD PROXIES ──
        for dead in dead_proxies:
            await run_in_db(remove_proxy, dead, user_id)

        await msg.edit_text(
            f"{section(E_CHAIN, 'Test', ' · done')}\n\n"
            f"╰ total  {bold(str(len(proxies)))} · "
            f"alive {bold(str(len(alive_proxies)))} · "
            f"dead  {bold(str(len(dead_proxies)))} (removed)\n"
        )

    else:
        await update.message.reply_text(f"{E_CROSS} Unknown subcommand. Use: list, add, remove, test, clear")


# ── /split  — split combo file into N-line parts ──────

async def split_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    reply = update.message.reply_to_message
    doc = None
    if reply and reply.document:
        doc = reply.document
    elif update.message.document:
        doc = update.message.document

    if not doc:
        await update.message.reply_text(
            f"{section(E_BOLT, 'Split')}\n\n╰ reply to .txt with /split 100\n"
        )
        return

    lines_per_part = None
    caption = update.message.caption or ""
    args = context.args or []
    if not args and caption:
        caption_parts = caption.split()
        for p in caption_parts[1:]:
            if p.isdigit():
                lines_per_part = int(p)
                break
    elif args:
        for a in args:
            if a.isdigit():
                lines_per_part = int(a)
                break

    try:
        file = await doc.get_file()
        data = await file.download_as_bytearray()
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        await update.message.reply_text(f"{E_CROSS} Failed to read file.")
        return

    raw_lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not raw_lines:
        await update.message.reply_text(f"{E_CROSS} File is empty.")
        return

    cards = await asyncio.to_thread(parse_cards, text, filter_expired=False)

    if not cards:
        await update.message.reply_text(f"{E_CROSS} No valid cards found in file.")
        return

    if not lines_per_part or lines_per_part <= 0:
        lines_per_part = len(cards)

    if lines_per_part >= len(cards):
        output = "\n".join(cards)
        buf = BytesIO(output.encode("utf-8"))
        buf.name = "plank_split.txt"
        await update.message.reply_document(
            buf,
            caption=f"{E_CHECK} Split {len(cards)} cards into CC|MM|YY|CVV format"
        )
        return

    num_parts = (len(cards) + lines_per_part - 1) // lines_per_part
    await update.message.reply_text(
        f"{section(E_INFO, 'Splitting File')}\n\n"
        f"   {E_ARROW} total cards · {bold(str(len(cards)))}\n"
        f"   {E_ARROW} per part    · {bold(str(lines_per_part))}\n"
        f"   {E_ARROW} parts       · {bold(str(num_parts))}\n\n"
        f"{separator(BRAND_NAME)}"
    )

    for i in range(num_parts):
        start = i * lines_per_part
        end = min(start + lines_per_part, len(cards))
        chunk = cards[start:end]
        output = "\n".join(chunk)
        buf = BytesIO(output.encode("utf-8"))
        buf.name = f"plank_split_part{i + 1}.txt"
        await update.message.reply_document(
            buf,
            caption=f"{E_CHECK} Part {i + 1}/{num_parts} — {len(chunk)} cards"
        )


# ── /genad  — generate address by country ─────────────

ADDRESSES = {
    "us": {"country": "United States", "emoji": "🇺🇸", "data": [
        {"name": "John Smith", "street": "123 Main St", "city": "New York", "state": "NY", "zip": "10001", "phone": "(212) 555-0123"},
        {"name": "Jane Doe", "street": "456 Oak Ave", "city": "Los Angeles", "state": "CA", "zip": "90001", "phone": "(310) 555-0456"},
        {"name": "Bob Wilson", "street": "789 Pine Rd", "city": "Chicago", "state": "IL", "zip": "60601", "phone": "(312) 555-0789"},
    ]},
    "uk": {"country": "United Kingdom", "emoji": "🇬🇧", "data": [
        {"name": "James Brown", "street": "10 Downing St", "city": "London", "state": "ENG", "zip": "SW1A 2AA", "phone": "+44 20 7946 0958"},
        {"name": "Emma Watson", "street": "221B Baker St", "city": "London", "state": "ENG", "zip": "NW1 6XE", "phone": "+44 20 7946 0123"},
    ]},
    "ca": {"country": "Canada", "emoji": "🇨🇦", "data": [
        {"name": "Liam Murphy", "street": "88 Queen St W", "city": "Toronto", "state": "ON", "zip": "M5J 2J3", "phone": "(416) 555-0198"},
        {"name": "Sophie Martin", "street": "200 Rue Sainte", "city": "Montreal", "state": "QC", "zip": "H2Y 1C6", "phone": "(514) 555-0234"},
    ]},
    "in": {"country": "India", "emoji": "🇮🇳", "data": [
        {"name": "Raj Patel", "street": "221B MG Road", "city": "Mumbai", "state": "MH", "zip": "400001", "phone": "+91 98765 43210"},
    ]},
    "au": {"country": "Australia", "emoji": "🇦🇺", "data": [
        {"name": "Jack Taylor", "street": "1 Martin Place", "city": "Sydney", "state": "NSW", "zip": "2000", "phone": "+61 2 9123 4567"},
    ]},
}


async def genad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    if not context.args:
        countries = ", ".join(f"{v['emoji']} {k.upper()}" for k, v in ADDRESSES.items())
        await update.message.reply_text(
            f"{section(E_EARTH, 'Generate Address')}\n\n"
            f"   {E_ARROW} /genad US\n"
            f"   {E_ARROW} available: {countries}\n\n"
            f"{separator(BRAND_NAME)}"
        )
        return

    country = context.args[0].strip().lower()
    addr_data = ADDRESSES.get(country)
    if not addr_data:
        await update.message.reply_text(f"{E_CROSS} Country '{country.upper()}' not available.")
        return

    addr = random.choice(addr_data["data"])
    addr_title = "Address  —  " + addr_data["emoji"] + " " + addr_data["country"]
    await update.message.reply_text(
        f"{section(E_EARTH, addr_title)}\n\n"
        f"   {E_ARROW} name    · {bold(addr['name'])}\n"
        f"   {E_ARROW} street  · {bold(addr['street'])}\n"
        f"   {E_ARROW} city    · {bold(addr['city'])}\n"
        f"   {E_ARROW} state   · {bold(addr['state'])}\n"
        f"   {E_ARROW} zip     · {bold(addr['zip'])}\n"
        f"   {E_ARROW} phone   · {bold(addr['phone'])}\n\n"
        f"{separator(BRAND_NAME)}"
    )


# ── /scr  — scrape cards from Telegram channels ──────

_CARD_RE = re.compile(CARD_PATTERN)


def _resolve_channel_username(text: str) -> str | None:
    """Extract public channel username from input. Returns None for private invites."""
    text = text.strip()

    if text.startswith(("https://", "http://")):
        text = text.split("://", 1)[1]

    if "joinchat/" in text or "/+" in text:
        return None

    if text.startswith("t.me/"):
        return text[5:].split("/")[0].split("?")[0]

    if text.startswith("@"):
        return text[1:]

    if re.match(r'^[a-zA-Z][a-zA-Z0-9_]{3,}$', text):
        return text

    return None


def _extract_cards_from_text(text: str) -> list[str]:
    """Extract card numbers from message text using regex."""
    if not text:
        return []

    cards = []
    for match in _CARD_RE.finditer(text):
        cc = match.group(1)
        mm = match.group(2).zfill(2)
        yy = match.group(3)
        cvv = match.group(4)

        if not (13 <= len(cc) <= 19):
            continue
        try:
            if not (1 <= int(mm) <= 12):
                continue
        except ValueError:
            continue
        if len(cvv) < 3:
            continue

        cards.append(f"{cc}|{mm}|{yy}|{cvv}")

    return cards


async def _scrape_tme_page(session: aiohttp.ClientSession, username: str,
                           before: int | None = None) -> tuple[list[str], int | None]:
    """Scrape one page of t.me/s/ web preview. Returns (html_messages, min_post_id)."""
    url = f"https://t.me/s/{username}"
    params = {}
    if before is not None:
        params["before"] = before

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 404:
                return [], None
            if resp.status != 200:
                return [], None
            html = await resp.text()
    except Exception:
        return [], None

    messages = re.findall(
        r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
        html, re.DOTALL
    )

    post_ids = [int(m) for m in re.findall(r'data-post="[^/]+/(\d+)"', html)]
    min_id = min(post_ids) if post_ids else None

    clean_messages = []
    for msg_html in messages:
        text = re.sub(r'<br\s*/?>', '\n', msg_html)
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&#39;', "'").replace('&quot;', '"')
        clean_messages.append(text)

    return clean_messages, min_id


async def scr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scrape cards from a public Telegram channel via web preview.
    Usage: /scr @channel 100
           /scr https://t.me/channel 500
    """
    if not await membership_guard(update, context):
        return

    user = update.effective_user
    await run_in_db(ensure_user, user.id, user.username or "")

    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            f"{section(E_FIRE, 'Card Scraper')}\n\n"
            f"   {E_ARROW} /scr @channel 100\n"
            f"   {E_ARROW} /scr https://t.me/channel 500\n"
            f"   {E_ARROW} /scr t.me/channel 200\n\n"
            f"   {E_ARROW} limit · {bold(str(SCRAPE_LIMIT_DEFAULT))} cards (owners: unlimited)\n"
            f"   {E_ARROW} scrapes public channels via web preview\n\n"
            f"{separator(BRAND_NAME)}"
        )
        return

    channel_input = context.args[0].strip()
    amount = SCRAPE_LIMIT_DEFAULT

    if len(context.args) >= 2:
        try:
            amount = int(context.args[1])
            if amount <= 0:
                await update.message.reply_text(f"{E_CROSS} Amount must be a positive number.")
                return
        except ValueError:
            await update.message.reply_text(
                f"{E_CROSS} Invalid amount: {context.args[1]}\n"
                f"   {E_ARROW} Usage: /scr @channel 100"
            )
            return

    if not is_owner(user.id) and amount > SCRAPE_LIMIT_DEFAULT:
        await update.message.reply_text(
            f"{E_CROSS} Scrape limit is {bold(str(SCRAPE_LIMIT_DEFAULT))} cards.\n"
            f"   {E_ARROW} Owners have no limit.\n"
            f"   {E_ARROW} Requested: {bold(str(amount))}"
        )
        return

    username = _resolve_channel_username(channel_input)
    if not username:
        await update.message.reply_text(
            f"{E_CROSS} Only public channels are supported.\n\n"
            f"   {E_ARROW} Use @username or https://t.me/username\n"
            f"   {E_ARROW} Private invite links are not supported."
        )
        return

    msg = await update.message.reply_text(
        f"{section(E_FIRE, 'Scraping Cards')}\n\n"
        f"   {E_ARROW} target · {bold(channel_input)}\n"
        f"   {E_ARROW} amount · {bold(str(amount))}\n"
        f"   {E_ARROW} status · Connecting...\n\n"
        f"{separator(BRAND_NAME)}"
    )

    all_cards: list[str] = []
    seen: set[str] = set()
    pages_scraped = 0
    before_id: int | None = None
    max_pages = 200
    last_update_time = time.time()

    try:
        async with aiohttp.ClientSession() as session:
            while len(all_cards) < amount and pages_scraped < max_pages:
                messages, min_id = await _scrape_tme_page(session, username, before_id)

                if not messages and pages_scraped == 0:
                    await msg.edit_text(
                        f"{E_CROSS} Channel not found or has no public posts.\n"
                        f"   {E_ARROW} channel · @{username}\n"
                        f"   {E_ARROW} Make sure the channel is public and has posts."
                    )
                    return

                if not messages:
                    break

                pages_scraped += 1

                for text in messages:
                    found = _extract_cards_from_text(text)
                    for card in found:
                        if card not in seen and len(all_cards) < amount:
                            seen.add(card)
                            all_cards.append(card)

                now = time.time()
                if now - last_update_time >= 3:
                    last_update_time = now
                    try:
                        await msg.edit_text(
                            f"{section(E_FIRE, 'Scraping Cards')}\n\n"
                            f"   {E_ARROW} target   · {bold(channel_input)}\n"
                            f"   {E_ARROW} found    · {bold(str(len(all_cards)))} / {amount}\n"
                            f"   {E_ARROW} pages    · {bold(str(pages_scraped))}\n"
                            f"   {E_ARROW} status   · Scraping...\n\n"
                            f"{separator(BRAND_NAME)}"
                        )
                    except Exception:
                        pass

                if min_id is None or (before_id is not None and min_id >= before_id):
                    break
                before_id = min_id

                await asyncio.sleep(0.5)

    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        await msg.edit_text(
            f"{E_CROSS} Scraping failed.\n"
            f"   {E_ARROW} {str(e)[:150]}"
        )
        if not all_cards:
            return

    if not all_cards:
        await msg.edit_text(
            f"{section(E_FIRE, 'Scrape Complete')}\n\n"
            f"   {E_ARROW} target   · {bold(channel_input)}\n"
            f"   {E_ARROW} pages    · {bold(str(pages_scraped))}\n"
            f"   {E_ARROW} found    · {bold('0')} cards\n"
            f"   {E_ARROW} No cards found in this channel.\n\n"
            f"{separator(BRAND_NAME)}"
        )
        return

    unique_cards = list(dict.fromkeys(all_cards))

    output = "\n".join(unique_cards)
    buf = BytesIO(output.encode("utf-8"))
    buf.name = f"plank_scraped_{len(unique_cards)}.txt"

    await msg.edit_text(
        f"{section(E_FIRE, 'Scrape Complete')}\n\n"
        f"   {E_ARROW} target   · {bold(channel_input)}\n"
        f"   {E_ARROW} pages    · {bold(str(pages_scraped))}\n"
        f"   {E_ARROW} found    · {bold(str(len(unique_cards)))} unique cards\n"
        f"   {E_ARROW} format   · CC|MM|YY|CVV\n\n"
        f"{separator(BRAND_NAME)}"
    )

    await update.message.reply_document(
        buf,
        caption=(
            f"{E_FIRE} Scraped {bold(str(len(unique_cards)))} cards "
            f"from {bold(channel_input)}\n"
            f"   {E_ARROW} by @{user.username or user.id}"
        ),
    )


# ── Helper ────────────────────────────────────────────

async def _extract_cards_for_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    reply = update.message.reply_to_message
    if reply and reply.document:
        try:
            file = await reply.document.get_file()
            data = await file.download_as_bytearray()
            text = data.decode("utf-8", errors="ignore")
            return await asyncio.to_thread(parse_cards, text)
        except Exception:
            return []

    if update.message.document:
        try:
            file = await update.message.document.get_file()
            data = await file.download_as_bytearray()
            text = data.decode("utf-8", errors="ignore")
            return await asyncio.to_thread(parse_cards, text)
        except Exception:
            return []

    if context.args:
        text = " ".join(context.args).replace(" ", "\n")
        return await asyncio.to_thread(parse_cards, text)

    caption = (update.message.caption or "") if update.message else ""
    if caption:
        cmd_removed = caption.split(maxsplit=1)[1] if " " in caption else ""
        return await asyncio.to_thread(parse_cards, cmd_removed)

    return []
