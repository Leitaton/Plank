"""
Plank — Admin handlers: /admin, /genplan, /site, /sitechk, /siteadd, and admin callbacks.
Restricted to OWNER_IDS.
"""

import os
import asyncio
import aiohttp
from io import BytesIO

from telegram import Update
from telegram.ext import ContextTypes

from config import PLANS, BRAND_NAME, OWNER_IDS, SHOPIFY_SITES_FILE, CHECKER_API_URL, MAX_SITE_TIME
from database import (
    ensure_user, get_user, set_plan, add_credits,
    ban_user, unban_user, get_all_users, get_user_count,
    create_redeem_code, get_total_hits, get_all_proxies,
    run_in_db,
)
from utils.emojis import (
    section, bold, separator,
    E_CROWN, E_GIFT, E_MONEY, E_CHECK, E_CROSS, E_ARROW, E_ERROR,
    E_USER, E_CHART, E_KEY, E_SHIELD, E_FIRE, E_CHAIN, E_BOLT,
    E_SPARKLE, E_SPARKLES, E_HEART, get_plan_emoji,
)
from utils.helpers import (
    is_owner, generate_redeem_code, parse_duration,
    credits_display, timestamp_now, proxy_to_url,
    progress_bar, progress_pct, parse_cards
)
from utils.keyboards import admin_keyboard, sitechk_keyboard
from utils.checkers import check_site
import uuid
import time

_site_sessions: dict[str, dict] = {}


def _owner_check(update: Update) -> bool:
    user = update.effective_user
    if not user or not is_owner(user.id):
        return False
    return True


async def admin_help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text(f"{E_CROSS} Owner-only command.")
        return

    text = (
        f"{section(E_CHART, 'Stats')}\n"
        f"╰ /stats  /broadcast  /allusers\n\n"
        f"{section(E_BOLT, 'Sites')}\n"
        f"╰ /site list|add|check\n"
        f"╰ /sitechk · reply to .txt\n"
        f"╰ /siteadd · reply to .txt\n"
        f"╰ /siteclean · clean .txt links\n"
        f"╰ /sitetest · check added sites\n"
        f"╰ /sitecard · set test card\n\n"
        f"{section(E_SHIELD, 'System')}\n"
        f"╰ /maintenance start|stop\n"
        f"╰ /reload  /backup\n"
    )
    await update.message.reply_text(text, reply_markup=admin_keyboard())

import os
async def maintenance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: toggle maintenance mode."""
    if not _owner_check(update):
        await update.message.reply_text(f"{E_CROSS} Owner-only command.")
        return

    if not context.args:
        await update.message.reply_text(
            f"{section(E_SHIELD, 'Maintenance Mode')}\n\n"
            f"╰ /maintenance start\n"
            f"╰ /maintenance stop\n"
        )
        return

    action = context.args[0].lower()
    if action == "start":
        with open("maintenance.flag", "w") as f:
            f.write("1")
        await update.message.reply_text(f"{E_CHECK} Maintenance mode {bold('started')}. Bot is locked for non-owners.")
    elif action == "stop":
        if os.path.exists("maintenance.flag"):
            os.remove("maintenance.flag")
        await update.message.reply_text(f"{E_CHECK} Maintenance mode {bold('stopped')}. Bot is open to all users.")
    else:
        await update.message.reply_text(f"{E_CROSS} Invalid action. Use start or stop.")
async def genplan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text(f"{E_CROSS} Owner-only command.")
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            f"{section(E_KEY, 'Generate Codes')}\n\n"
            f"╰ /genplan {{plan}} {{duration}} {{qty}}\n"
            f"╰ plans: dirt, cobblestone, diamond, bedrock\n"
            f"╰ ex: /genplan diamond 30d 5\n"
        )
        return

    plan_name = context.args[0].strip().lower()
    duration_str = context.args[1].strip()
    try:
        quantity = int(context.args[2].strip())
    except ValueError:
        await update.message.reply_text(f"{E_SPARKLE} invalid quantity")
        return

    if plan_name not in PLANS:
        await update.message.reply_text(f"{E_SPARKLE} invalid plan · {', '.join(PLANS.keys())}")
        return

    if quantity < 1 or quantity > 100:
        await update.message.reply_text(f"{E_SPARKLE} qty must be 1-100")
        return

    try:
        duration_sec = parse_duration(duration_str)
    except (ValueError, IndexError):
        await update.message.reply_text(f"{E_SPARKLE} invalid duration · use 7d, 30d, 1w, 1m")
        return

    codes = []
    for _ in range(quantity):
        code = generate_redeem_code(plan_name)
        await run_in_db(create_redeem_code, code, plan_name, duration_sec, update.effective_user.id)
        codes.append(code)

    plan_info = PLANS[plan_name]
    days = duration_sec // 86400

    codes_text = "\n".join(f"╰ <code>{c}</code>" for c in codes)
    await update.message.reply_text(
        f"{section(E_KEY, f'Generated {quantity} Codes')}\n\n"
        f"╰ plan     · {get_plan_emoji(plan_name)} {bold(plan_info['display'])}\n"
        f"╰ duration · {bold(f'{days} days')}\n\n"
        f"{codes_text}\n"
    )


async def setplan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text(f"{E_CROSS} Owner-only command.")
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            f"╰ /setplan {{user_id}} {{plan}} {{duration}}\n"
            f"╰ ex: /setplan 123456789 diamond 30d"
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E_SPARKLE} invalid user ID")
        return

    plan_name = context.args[1].strip().lower()
    if plan_name not in PLANS:
        await update.message.reply_text(f"{E_SPARKLE} invalid plan")
        return

    try:
        duration_sec = parse_duration(context.args[2])
    except (ValueError, IndexError):
        await update.message.reply_text(f"{E_SPARKLE} invalid duration")
        return

    await run_in_db(ensure_user, target_id)
    await run_in_db(set_plan, target_id, plan_name, duration_sec)
    plan_info = PLANS[plan_name]

    await update.message.reply_text(
        f"{E_CHECK} set {bold(plan_info['display'])} for {target_id} ({duration_sec // 86400}d)"
    )


async def addcredits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text(f"{E_CROSS} Owner-only command.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(f"╰ /addcredits {{user_id}} {{amount}}")
        return

    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text(f"{E_SPARKLE} invalid args")
        return

    await run_in_db(ensure_user, target_id)
    await run_in_db(add_credits, target_id, amount)
    await update.message.reply_text(f"{E_CHECK} +{amount} credits → {target_id}")


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        return

    if not context.args:
        await update.message.reply_text(f"╰ /ban {{user_id}}")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E_SPARKLE} invalid user ID")
        return

    await run_in_db(ban_user, target_id)
    await update.message.reply_text(f"{E_SHIELD} {target_id} banned")


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        return

    if not context.args:
        await update.message.reply_text(f"╰ /unban {{user_id}}")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E_SPARKLE} invalid user ID")
        return

    await run_in_db(unban_user, target_id)
    await update.message.reply_text(f"{E_CHECK} {target_id} unbanned")


async def userinfo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        return

    if not context.args:
        await update.message.reply_text(f"╰ /userinfo {{user_id}}")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E_SPARKLE} invalid user ID")
        return

    user = await run_in_db(get_user, target_id)
    if not user:
        await update.message.reply_text(f"{E_SPARKLE} user not found")
        return

    plan_info = PLANS.get(user["plan"], PLANS["dirt"])
    cr = user["credits"]

    await update.message.reply_text(
        f"{section(E_USER, f'User {target_id}')}\n\n"
        f"╰ username · @{user['username'] or 'N/A'}\n"
        f"╰ plan     · {get_plan_emoji(user['plan'])} {bold(plan_info['display'])}\n"
        f"╰ credits  · {bold(credits_display(cr))}\n"
        f"╰ banned   · {bold('Yes' if user['banned'] else 'No')}\n"
    )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text(f"{E_CROSS} Owner-only command.")
        return

    total_users = await run_in_db(get_user_count)
    total_hits = await run_in_db(get_total_hits)
    shopify_hits = await run_in_db(get_total_hits, "Shopify")

    await update.message.reply_text(
        f"{section(E_CHART, 'Stats')}\n\n"
        f"╰ users   · {bold(str(total_users))}\n"
        f"╰ total   · {bold(str(total_hits))} checks\n"
        f"╰ shopify · {bold(str(shopify_hits))}\n"
    )


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        return

    if not context.args:
        await update.message.reply_text(f"╰ /broadcast {{message}}")
        return

    message = " ".join(context.args)
    users = await run_in_db(get_all_users)
    sent = 0
    failed = 0

    for u in users:
        try:
            await context.bot.send_message(u["user_id"], message)
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"{section(E_CHECK, 'broadcast')} · {sent} sent · {failed} failed"
    )


async def allusers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        return

    users = await run_in_db(get_all_users)
    if not users:
        await update.message.reply_text(f"{section(E_SPARKLE, 'no users')}")
        return

    text = f"{section(E_USER, f'Users ({len(users)})')}\n\n"
    for u in users[:50]:
        plan_info = PLANS.get(u["plan"], PLANS["dirt"])
        plan_emoji = get_plan_emoji(u["plan"])
        text += (
            f"╰ {u['user_id']} · @{u['username'] or 'N/A'} "
            f"· {plan_emoji} {plan_info['display']}\n"
        )
    if len(users) > 50:
        text += f"\n╰ ... and {len(users) - 50} more"
    await update.message.reply_text(text)


# ── Admin callback handler ────────────────────────────

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        try:
            await query.answer("Owner-only.", show_alert=True)
        except Exception:
            pass
        return

    data = query.data
    try:
        await query.answer()
    except Exception:
        pass

    if data == "admin_users":
        users = await run_in_db(get_all_users)
        text = f"{section(E_USER, f'Users ({len(users)})')}\n\n"
        for u in users[:30]:
            plan_info = PLANS.get(u["plan"], PLANS["dirt"])
            text += f"╰ {u['user_id']} · @{u['username'] or 'N/A'} · {plan_info['display']}\n"
        await query.message.reply_text(text)

    elif data == "admin_stats":
        total_users = await run_in_db(get_user_count)
        total_hits = await run_in_db(get_total_hits)
        await query.message.reply_text(
            f"{section(E_CHART, 'Quick Stats')}\n\n"
            f"╰ users  · {bold(str(total_users))}\n"
            f"╰ checks · {bold(str(total_hits))}\n"
        )

    elif data == "admin_genplan":
        await query.message.reply_text(
            f"╰ /genplan {{plan}} {{duration}} {{qty}}\n"
            f"╰ ex: /genplan diamond 30d 5"
        )

    elif data == "admin_setplan":
        await query.message.reply_text(
            f"╰ /setplan {{user_id}} {{plan}} {{duration}}\n"
            f"╰ ex: /setplan 123456789 diamond 30d"
        )

    elif data == "admin_addcredits":
        await query.message.reply_text(
            f"╰ /addcredits {{user_id}} {{amount}}\n"
            f"╰ ex: /addcredits 123456789 5000"
        )

    elif data == "admin_ban":
        await query.message.reply_text(
            f"╰ /ban {{user_id}} or /unban {{user_id}}"
        )

    elif data == "admin_broadcast":
        await query.message.reply_text(
            f"╰ /broadcast {{message}}"
        )

    elif data == "admin_proxies":
        proxies = await run_in_db(get_all_proxies, False)
        await query.message.reply_text(
            f"{section(E_CHAIN, f'Proxies ({len(proxies)})')}\n\n"
            f"╰ /proxy list|add|remove|test\n"
        )


# ── /site command (simple management) ────────────────

def _load_sites() -> list[str]:
    if not os.path.exists(SHOPIFY_SITES_FILE):
        return []
    with open(SHOPIFY_SITES_FILE, "r") as f:
        return [l.strip() for l in f.readlines() if l.strip()]


def _save_sites(sites: list[str]):
    with open(SHOPIFY_SITES_FILE, "w") as f:
        f.write("\n".join(sites) + "\n" if sites else "")


def _invalidate_caches():
    try:
        from utils.checkers import invalidate_sites_cache as inv_checkers
        inv_checkers()
    except Exception:
        pass
    try:
        from handlers.gates import invalidate_sites_cache as inv_gates
        inv_gates()
    except Exception:
        pass


async def site_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text(f"{section(E_SPARKLE, 'owner-only')}")
        return

    if not context.args:
        await update.message.reply_text(
            f"{section(E_BOLT, 'Site Management')}\n\n"
            f"╰ /site list  — show all sites\n"
            f"╰ /site add   — reply to .txt file\n"
            f"╰ /site check — validate + remove dead\n\n"
            f"╰ /sitechk · check sites via API\n"
            f"╰ /siteadd · add validated sites\n"
        )
        return

    sub = context.args[0].lower()

    if sub == "list":
        sites = await asyncio.to_thread(_load_sites)
        if not sites:
            await update.message.reply_text(
                f"{section(E_SPARKLE, 'no sites')} · /site add or /siteadd"
            )
            return

        text = f"{section(E_BOLT, f'Sites ({len(sites)})')}\n\n"
        for s in sites[:30]:
            text += f"╰ {s}\n"
        if len(sites) > 30:
            text += f"\n╰ ... and {len(sites) - 30} more"
        await update.message.reply_text(text)

    elif sub == "add":
        reply = update.message.reply_to_message
        if not reply or not reply.document:
            await update.message.reply_text(
                f"{section(E_SPARKLE, 'reply to a .txt file with /site add')}"
            )
            return

        msg = await update.message.reply_text(f"{section(E_BOLT, 'loading sites...')}")

        try:
            file = await reply.document.get_file()
            data = await file.download_as_bytearray()
            text = data.decode("utf-8", errors="ignore")
            new_sites = [l.strip() for l in text.splitlines() if l.strip()]
        except Exception:
            await msg.edit_text(f"{section(E_SPARKLE, 'failed to read file')}")
            return

        if not new_sites:
            await msg.edit_text(f"{section(E_SPARKLE, 'no sites in file')}")
            return

        existing = set(await asyncio.to_thread(_load_sites))
        added = [s for s in new_sites if s not in existing]

        if not added:
            await msg.edit_text(f"{section(E_CHECK, 'all sites already exist')}")
            return

        all_sites = list(existing) + added
        await asyncio.to_thread(_save_sites, all_sites)
        _invalidate_caches()

        await msg.edit_text(
            f"{section(E_CHECK, 'Sites Added')}\n\n"
            f"╰ new   · {bold(str(len(added)))}\n"
            f"╰ total · {bold(str(len(all_sites)))}\n"
        )

    elif sub == "check":
        sites = await asyncio.to_thread(_load_sites)
        if not sites:
            await update.message.reply_text(f"{section(E_SPARKLE, 'no sites to check')}")
            return

        msg = await update.message.reply_text(
            f"{section(E_BOLT, f'checking {len(sites)} sites via API...')}"
        )

        alive_sites = []
        dead_sites = []
        semaphore = asyncio.Semaphore(45)

        async def check_one(site: str):
            async with semaphore:
                result = await check_site(site)
                is_valid = (
                    result.get("valid", False) is True
                    and result.get("card_response", "").upper() == "CARD_DECLINED"
                )
                if is_valid:
                    price = result.get("price", "0.00")
                    check_time = result.get("time", "")
                    
                    is_fast = False
                    try:
                        time_val = float(str(check_time).replace("s", ""))
                        if time_val <= MAX_SITE_TIME:
                            is_fast = True
                    except Exception:
                        pass

                    if is_fast:
                        alive_sites.append((site, f"VALID (${price})"))
                    else:
                        dead_sites.append((site, f"SLOW ({check_time})"))
                else:
                    reason = result.get("card_response", result.get("error", "DEAD"))
                    dead_sites.append((site, reason))

        tasks = [asyncio.create_task(check_one(s)) for s in sites]
        await asyncio.gather(*tasks)

        await asyncio.to_thread(_save_sites, [s for s, _ in alive_sites])
        _invalidate_caches()

        result_text = (
            f"{section(E_CHECK, 'Site Check Done')}\n\n"
            f"╰ checked · {bold(str(len(sites)))}\n"
            f"╰ alive   · {bold(str(len(alive_sites)))}\n"
            f"╰ removed · {bold(str(len(dead_sites)))}\n"
        )
        if dead_sites[:5]:
            result_text += f"\n{section(E_CROSS, 'Removed')}\n"
            for s, r in dead_sites[:5]:
                result_text += f"╰ {s} — {r}\n"
            if len(dead_sites) > 5:
                result_text += f"╰ ... +{len(dead_sites) - 5} more\n"
        await msg.edit_text(result_text)

    else:
        await update.message.reply_text(
            f"{section(E_SPARKLE, 'unknown · use /site list|add|check')}"
        )


# ── /sitechk command — check sites via external API ──

async def _execute_site_check(update: Update, context: ContextTypes.DEFAULT_TYPE, sites: list[str], title="Site Checker"):
    total = len(sites)
    session_id = uuid.uuid4().hex[:8]
    
    state = {
        "id": session_id,
        "user_id": update.effective_user.id,
        "sites": sites,
        "total": total,
        "processed": 0,
        "fast": [],
        "slow": [],
        "invalid": [],
        "error": [],
        "stopped": False,
        "last_active": time.time(),
        "title": title
    }
    _site_sessions[session_id] = state

    status_msg = await update.message.reply_text(
        f"{E_SPARKLES} <b>{title}</b> · starting...\n\n"
        f"{E_HEART} progress: {progress_bar(0, total)} 0/{total}\n\n"
        f"{E_CHECK} 0 · {E_CROSS} 0 · {E_ERROR} 0\n",
        reply_markup=sitechk_keyboard(session_id)
    )
    
    state["msg_id"] = status_msg.message_id
    state["chat_id"] = update.effective_chat.id

    last_update = [time.time()]
    edit_lock = asyncio.Lock()

    async def _do_edit(finished=False):
        pct = progress_pct(state["processed"], total)
        bar = progress_bar(state["processed"], total)
        status = "done" if finished else ("stopped" if state["stopped"] else f"{pct}%")

        valid_count = len(state["fast"]) + len(state["slow"])
        update_text = (
            f"{E_SPARKLES} <b>{title}</b> · {status}\n\n"
            f"{E_HEART} progress: {bar} <b>{state['processed']}/{total}</b>\n\n"
            f"{E_CHECK} <b>{valid_count}</b> (Fast: {len(state['fast'])}) · "
            f"{E_CROSS} <b>{len(state['invalid'])}</b> · "
            f"{E_ERROR} <b>{len(state['error'])}</b>\n"
        )

        all_valid = state["fast"] + state["slow"]
        if all_valid:
            for v in all_valid[-3:]:
                update_text += f"\n{E_HEART} {E_CHECK} {v['site']} · ${v['price']}"

        try:
            await context.bot.edit_message_text(
                chat_id=state["chat_id"],
                message_id=state["msg_id"],
                text=update_text,
                reply_markup=sitechk_keyboard(
                    session_id,
                    fast=len(state["fast"]),
                    slow=len(state["slow"]),
                    invalid=len(state["invalid"]),
                    error=len(state["error"]),
                    stopped=state["stopped"] or finished
                )
            )
        except Exception:
            pass

    async def trigger_status_update(force=False):
        now = time.time()
        state["last_active"] = now
        is_final = state["processed"] == total
        if is_final or force or (now - last_update[0] >= 5.0):
            if is_final:
                async with edit_lock:
                    last_update[0] = now
                    await _do_edit(finished=True)
            else:
                if not edit_lock.locked():
                    async with edit_lock:
                        now = time.time()
                        if now - last_update[0] >= 5.0 or force:
                            last_update[0] = now
                            await _do_edit()

    semaphore = asyncio.Semaphore(45)

    async def _check_one(site: str):
        if state["stopped"]:
            return
        async with semaphore:
            result = await check_site(site)

        if state["stopped"]:
            return

        is_valid = result.get("valid", False) is True

        state["processed"] += 1

        if is_valid:
            price = result.get("price", "?")
            product = result.get("product", "?")
            gate = result.get("gate", "?")
            check_time = result.get("time", "?")
            
            is_fast = False
            try:
                time_val = float(str(check_time).replace("s", ""))
                if time_val <= MAX_SITE_TIME:
                    is_fast = True
            except Exception:
                pass

            if is_fast:
                state["fast"].append({
                    "site": site,
                    "price": price,
                    "product": product,
                    "gate": gate,
                    "time": check_time,
                })
            else:
                state["slow"].append({
                    "site": site,
                    "price": price,
                    "product": product,
                    "gate": gate,
                    "time": check_time,
                })
        elif result.get("error"):
            state["error"].append((site, result["error"]))
        else:
            resp = result.get("card_response", "UNKNOWN")
            state["invalid"].append((site, resp))

        await trigger_status_update()

    tasks = [asyncio.create_task(_check_one(s)) for s in sites]
    await asyncio.gather(*tasks)
    
    if not state["stopped"]:
        await trigger_status_update(force=True)

async def sitechk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: reply to a .txt file containing Shopify site list."""
    if not _owner_check(update):
        await update.message.reply_text(f"{section(E_SPARKLE, 'owner-only')}")
        return

    reply = update.message.reply_to_message
    if not reply or not reply.document:
        await update.message.reply_text(
            f"{section(E_BOLT, 'Site Checker')}\n\n"
            f"╰ reply to a .txt file with /sitechk\n"
            f"╰ file should have one site per line\n"
        )
        return

    try:
        file = await reply.document.get_file()
        data = await file.download_as_bytearray()
        text = data.decode("utf-8", errors="ignore")
        sites = [l.strip() for l in text.splitlines() if l.strip()]
    except Exception:
        await update.message.reply_text(f"{section(E_SPARKLE, 'failed to read file')}")
        return

    if not sites:
        await update.message.reply_text(f"{section(E_SPARKLE, 'no sites found in file')}")
        return

    sites = list(dict.fromkeys(sites))
    await _execute_site_check(update, context, sites, title="Site Checker")


# ── /siteadd command — add validated sites ────────────

async def siteadd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: reply to a .txt file (e.g. valid_sites.txt) with /siteadd
    to add the sites to the bot's Shopify sites list.
    """
    if not _owner_check(update):
        await update.message.reply_text(f"{section(E_SPARKLE, 'owner-only')}")
        return

    reply = update.message.reply_to_message
    if not reply or not reply.document:
        await update.message.reply_text(
            f"{section(E_BOLT, 'Add Sites')}\n\n"
            f"╰ reply to valid_sites.txt with /siteadd\n"
            f"╰ use /sitechk first to validate\n"
        )
        return

    try:
        file = await reply.document.get_file()
        data = await file.download_as_bytearray()
        text = data.decode("utf-8", errors="ignore")
        new_sites = [l.strip() for l in text.splitlines() if l.strip()]
    except Exception:
        await update.message.reply_text(f"{section(E_SPARKLE, 'failed to read file')}")
        return

    if not new_sites:
        await update.message.reply_text(f"{section(E_SPARKLE, 'no sites in file')}")
        return

    existing = set(await asyncio.to_thread(_load_sites))
    added = [s for s in new_sites if s not in existing]

    if not added:
        await update.message.reply_text(f"{section(E_CHECK, 'all sites already exist')}")
        return

    all_sites = list(existing) + added
    await asyncio.to_thread(_save_sites, all_sites)
    _invalidate_caches()

    await update.message.reply_text(
        f"{section(E_CHECK, 'Sites Added')}\n\n"
        f"╰ new   · {bold(str(len(added)))}\n"
        f"╰ total · {bold(str(len(all_sites)))}\n"
    )


async def sitetest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: test the sites already added to the bot."""
    if not _owner_check(update):
        await update.message.reply_text(f"{section(E_SPARKLE, 'owner-only')}")
        return

    sites = await asyncio.to_thread(_load_sites)
    if not sites:
        await update.message.reply_text(f"{section(E_SPARKLE, 'no sites added to the bot')}")
        return

    sites = list(dict.fromkeys(sites))
    await _execute_site_check(update, context, sites, title="Site Tester")


async def sitecard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text(f"{section(E_SPARKLE, 'owner-only')}")
        return

    cards = []
    reply = update.message.reply_to_message
    if reply and reply.document:
        try:
            file = await reply.document.get_file()
            data = await file.download_as_bytearray()
            text = data.decode("utf-8", errors="ignore")
            cards = await asyncio.to_thread(parse_cards, text)
        except Exception:
            await update.message.reply_text(f"{section(E_SPARKLE, 'failed to read file')}")
            return
    elif context.args:
        text = " ".join(context.args)
        cards = await asyncio.to_thread(parse_cards, text)

    if not cards:
        await update.message.reply_text(
            f"{section(E_BOLT, 'Site Check Cards')}\n\n"
            f"╰ reply to a .txt file containing cards\n"
            f"╰ or type /sitecard CC|MM|YY|CVV\n"
        )
        return

    try:
        with open("site_cards.txt", "w") as f:
            f.write("\n".join(cards) + "\n")
    except Exception:
        await update.message.reply_text(f"{section(E_SPARKLE, 'failed to save cards')}")
        return

    await update.message.reply_text(
        f"{section(E_CHECK, 'Site Cards Updated')}\n\n"
        f"╰ added {len(cards)} test cards\n"
    )


async def sitechk_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(query.from_user.id):
        try:
            await query.answer("Owner-only.", show_alert=True)
        except Exception:
            pass
        return

    parts = query.data.split("_")
    action = parts[0]

    if action == "sstop":
        session_id = parts[1]
        state = _site_sessions.get(session_id)
        if not state:
            try:
                await query.answer("session expired", show_alert=True)
            except Exception:
                pass
            return
        state["stopped"] = True
        try:
            await query.answer(f"{E_STOP} stopping...")
        except Exception:
            pass
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                reply_markup=sitechk_keyboard(
                    session_id,
                    fast=len(state["fast"]),
                    slow=len(state["slow"]),
                    invalid=len(state["invalid"]),
                    error=len(state["error"]),
                    stopped=True
                )
            )
        except Exception:
            pass
        return

    if action == "sview":
        category = parts[1]
        session_id = parts[2]
        state = _site_sessions.get(session_id)
        if not state:
            try:
                await query.answer("session expired", show_alert=True)
            except Exception:
                pass
            return

        results = state.get(category, [])
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

        if category in ("fast", "slow", "valid"):
            content = "\n".join(v["site"] for v in results)
        else:
            content = "\n".join(f"{s} | {r}" for s, r in results)

        buf = BytesIO(content.encode("utf-8"))
        buf.name = f"plank_sitechk_{category}.txt"
        await query.message.reply_document(
            buf,
            caption=f"{E_HEART} {category.upper()} · {len(results)}"
        )

import re
async def siteclean_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: parses a txt file and returns only the URLs."""
    if not _owner_check(update):
        await update.message.reply_text(f"{section(E_SPARKLE, 'owner-only')}")
        return

    reply = update.message.reply_to_message
    if not reply or not reply.document:
        await update.message.reply_text(
            f"{section(E_BOLT, 'Site Cleaner')}\n\n"
            f"╰ reply to a .txt file with /siteclean\n"
            f"╰ extracts only the https:// links\n"
        )
        return

    try:
        file = await reply.document.get_file()
        data = await file.download_as_bytearray()
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        await update.message.reply_text(f"{section(E_SPARKLE, 'failed to read file')}")
        return

    urls = []
    # Match standard https://... domains
    url_pattern = re.compile(r"https?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
    for line in text.splitlines():
        match = url_pattern.search(line)
        if match:
            url = match.group(0)
            urls.append(url)
    
    if not urls:
        await update.message.reply_text(f"{section(E_SPARKLE, 'no urls found in file')}")
        return

    urls = list(dict.fromkeys(urls)) # dedup
    content = "\n".join(urls)
    buf = BytesIO(content.encode("utf-8"))
    buf.name = "cleaned_sites.txt"
    await update.message.reply_document(
        buf,
        caption=(
            f"{section(E_CHECK, 'Cleaned Sites')}\n"
            f"╰ extracted {len(urls)} links"
        )
    )



async def reload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text(f"{E_CROSS} Owner-only command.")
        return
    try:
        from utils.emojis import reload_emojis
        reload_emojis()
        _invalidate_caches()
        await update.message.reply_text(f"{E_CHECK} Emojis reloaded & sites cache invalidated successfully.")
    except Exception as e:
        await update.message.reply_text(f"{E_CROSS} Error during reload: {str(e)}")


async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: zip all project source files and send to the owner."""
    if not _owner_check(update):
        await update.message.reply_text(f"{E_CROSS} Owner-only command.")
        return

    import zipfile
    from io import BytesIO

    status_msg = await update.message.reply_text("📦 Preparing backup of all source files...")

    try:
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            for root, dirs, files in os.walk(root_dir):
                # Exclude runtime/virtualenv/git/cache directories
                dirs[:] = [d for d in dirs if d not in ('venv', '.git', '__pycache__', '.antigravitycli', '.idea', '.vscode')]
                for file in files:
                    # Exclude database files to prevent large sizes/corruption during live zip
                    if file.startswith("plankbot.db") or file.endswith(".pyc"):
                        continue
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, root_dir)
                    zip_file.write(file_path, arcname)
        
        zip_buffer.seek(0)
        zip_buffer.name = "plankbot_backup.zip"
        
        await update.message.reply_document(
            document=zip_buffer,
            caption=(
                f"{section(E_CHECK, 'PlankBot Source Backup')}\n\n"
                f"╰ here is the backup of the bot's source files, excluding the database and virtual environment."
            )
        )
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"{E_CROSS} Failed to create backup: {str(e)}")


