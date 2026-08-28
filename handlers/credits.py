"""
Plank — Credit & plan commands: /daily, /balance, /redeem.
"""

import time

from telegram import Update
from telegram.ext import ContextTypes

from config import PLANS, DAILY_COOLDOWN_HOURS, BRAND_NAME, HIT_PUBLIC_CHAT_ID
from database import (
    ensure_user, get_user, add_credits, set_last_daily,
    set_plan, redeem_code as db_redeem, run_in_db,
    check_redeem_code_validity, get_profile_stats
)
from utils.emojis import (
    section, bold, separator, E_MONEY, E_GIFT, E_ARROW, E_CHECK, E_CROSS, E_STAR, E_CLOCK, E_HEART, E_WARN, get_emoji, get_plan_emoji,
    E_SECTION_OPEN, E_SECTION_CLOSE, E_USER, E_PERFORMANCE
)
from utils.helpers import credits_display, get_plan_info
from handlers.start import membership_guard


async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    user = update.effective_user
    db_user = await run_in_db(ensure_user, user.id, user.username or "")

    cooldown = DAILY_COOLDOWN_HOURS * 3600
    elapsed = time.time() - db_user["last_daily"]
    if elapsed < cooldown:
        remaining = cooldown - elapsed
        hours = int(remaining // 3600)
        mins = int((remaining % 3600) // 60)
        await update.message.reply_text(
            f"{section(E_CLOCK, 'Daily Claimed')} · next in {bold(f'{hours}h {mins}m')}\n"
        )
        return

    plan_info = get_plan_info(db_user["plan"])
    bonus = plan_info.get("daily_bonus", 25)
    await run_in_db(add_credits, user.id, bonus)
    await run_in_db(set_last_daily, user.id)

    updated = await run_in_db(get_user, user.id)
    await update.message.reply_text(
        f"{section(E_GIFT, 'Daily')}\n\n"
        f"╰ +{bold(str(bonus))} credits · total {bold(credits_display(updated['credits']))}\n"
    )


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    user = update.effective_user
    db_user = await run_in_db(ensure_user, user.id, user.username or "")
    cr = db_user["credits"]
    plan_info = get_plan_info(db_user["plan"])

    # Resolve plan emoji from dynamic config
    plan_emoji = get_plan_emoji(db_user["plan"])

    await update.message.reply_text(
        f"{section(E_MONEY, 'Balance')}\n\n"
        f"╰ {plan_emoji} {bold(plan_info['display'])} · "
        f"{bold(credits_display(cr))} cr · "
        f"{plan_info['workers']}w\n"
    )


PLAN_LEVELS = {
    "dirt": 0,
    "cobblestone": 1,
    "diamond": 2,
    "bedrock": 3,
}

_redeem_cooldowns = {}
REDEEM_COOLDOWN_SEC = 5


async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    user = update.effective_user
    db_user = await run_in_db(ensure_user, user.id, user.username or "")

    # 1. Cooldown Check
    now = time.time()
    last_redeem = _redeem_cooldowns.get(user.id, 0)
    if now - last_redeem < REDEEM_COOLDOWN_SEC:
        remaining = int(REDEEM_COOLDOWN_SEC - (now - last_redeem))
        await update.message.reply_text(
            f"{E_WARN} Please wait {bold(f'{remaining}s')} before using /redeem again."
        )
        return

    _redeem_cooldowns[user.id] = now

    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            f"{section(E_WARN, '/redeem PLANK-PLAN-XXXXXXXX')}\n"
        )
        return

    code = context.args[0].strip().upper()

    # 2. Check validity first (without consuming the code)
    code_info = await run_in_db(check_redeem_code_validity, code)
    if not code_info:
        await update.message.reply_text(
            f"{section(E_CROSS, 'invalid or used code')}\n"
        )
        return

    plan = code_info["plan"]
    duration = code_info["duration_sec"]

    # 3. Check plan tier comparison
    current_plan = db_user["plan"]
    if db_user["plan_expires"] > 0 and time.time() > db_user["plan_expires"]:
        current_plan = "dirt"

    current_level = PLAN_LEVELS.get(current_plan, 0)
    new_level = PLAN_LEVELS.get(plan, 0)

    if new_level < current_level:
        await update.message.reply_text(
            f"{E_CROSS} you already have a higher plan"
        )
        return

    # 4. Consume/redeem the code now
    result = await run_in_db(db_redeem, code, user.id)
    if not result:
        await update.message.reply_text(
            f"{section(E_CROSS, 'invalid or used code')}\n"
        )
        return

    # 5. Apply the plan/credits (supports stacking)
    new_expires, new_credits, is_stacked = await run_in_db(set_plan, user.id, plan, duration)
    plan_info = get_plan_info(plan)
    days = duration // 86400
    plan_emoji = get_plan_emoji(plan)

    # 6. PM confirmation message to the user
    await update.message.reply_text(
        f"{section(E_STAR, 'Redeemed')}\n\n"
        f"╰ {plan_emoji} {bold(plan_info['display'])} · {bold(f'{days}d')} · {plan_info['workers']}w\n"
    )

    # 7. Group Notification (like the charged message)
    if HIT_PUBLIC_CHAT_ID:
        uname = user.username or user.first_name
        if is_stacked:
            total_days = round((new_expires - time.time()) / 86400)
            stack_count = max(1, round((new_expires - time.time()) / duration))
            public_text = (
                f"{E_STAR} <b>Plan Stacked</b> · @{uname}\n\n"
                f"{E_HEART} plan: {plan_emoji} {plan_info['display']}\n"
                f"{E_HEART} stacked: x{stack_count}\n"
                f"{E_HEART} total duration: {total_days} days\n"
            )
        else:
            public_text = (
                f"{E_STAR} <b>Plan Redeemed</b> · @{uname}\n\n"
                f"{E_HEART} plan: {plan_emoji} {plan_info['display']}\n"
                f"{E_HEART} duration: {days} days\n"
            )
        try:
            await context.bot.send_message(HIT_PUBLIC_CHAT_ID, public_text)
        except Exception:
            pass


async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    user = update.effective_user
    db_user = await run_in_db(ensure_user, user.id, user.username or "")
    
    stats = await run_in_db(get_profile_stats, user.id)
    if not stats:
        await update.message.reply_text("Error loading profile stats.")
        return
        
    username = user.username or user.first_name or "User"
    
    joined = stats["joined_at"]
    joined_time = joined if joined > 0 else time.time()
    age_days = int((time.time() - joined_time) / 86400)
    
    plan = stats["plan"]
    plan_info = get_plan_info(plan)
    plan_display = plan_info["display"].upper()
    plan_emoji = get_plan_emoji(plan)
    
    plan_expires = stats["plan_expires"]
    if plan == "dirt":
        expiry_str = "Lifetime"
    elif plan_expires <= 0:
        expiry_str = "Lifetime"
    else:
        remaining_sec = plan_expires - time.time()
        if remaining_sec <= 0:
            expiry_str = "Expired"
        else:
            exp_days = int(remaining_sec / 86400)
            exp_hours = int((remaining_sec % 86400) / 3600)
            expiry_str = f"{exp_days}d {exp_hours}h"
            
    bal_str = credits_display(stats["credits"])
    
    workers = plan_info.get("workers", 5)
    cooldown = plan_info.get("cooldown", 2)
    mass_limit = plan_info.get("mass_limit", 100)
    daily_bonus = plan_info.get("daily_bonus", 25)
    
    if workers <= 5:
        speed_label = "Slow"
    elif workers <= 20:
        speed_label = "Medium"
    elif workers <= 40:
        speed_label = "Fast"
    else:
        speed_label = "Turbo"
    speed_str = f"{speed_label} ({workers} workers)"
    
    total_checks = stats["total_checks"]
    hits_count = stats["hits_count"]
    pct = (hits_count / total_checks * 100) if total_checks > 0 else 0.0
    
    total_checks_str = f"{total_checks:,}"
    hits_str = f"{hits_count:,} ({pct:.1f}%)"
    
    rank_str = f"#{stats['rank']} of {stats['total_users']}"
    
    cooldown_str = f"{cooldown}s" if cooldown > 0 else "None"
    
    text = (
        f"{E_SECTION_OPEN} {E_STAR} {E_SECTION_CLOSE}  {bold('PROFILE  —  User Card')}\n\n"
        
        f"{E_SECTION_OPEN} {E_USER} {E_SECTION_CLOSE}  {bold('Identity')}\n"
        f"▸  <code>name</code> · {bold(username)}\n"
        f"▸  <code>id</code>   · {bold(str(user.id))}\n"
        f"▸  <code>age</code>  · {bold(f'{age_days}d')}\n\n"
        
        f"{E_SECTION_OPEN} {E_MONEY} {E_SECTION_CLOSE}  {bold('Plan')}\n"
        f"▸  <code>tier</code>  · {plan_emoji} {bold(plan_display)}\n"
        f"▸  <code>exp</code>   · {bold(expiry_str)}\n"
        f"▸  <code>bal</code>   · {bold(bal_str)} {bold('credits')}\n"
        f"▸  <code>spd</code>   · {bold(speed_str)}\n"
        f"▸  <code>cd</code>    · {bold(cooldown_str)}\n"
        f"▸  <code>mass</code>  · {bold(f'{mass_limit:,}')}\n"
        f"▸  <code>daily</code> · +{bold(str(daily_bonus))}\n\n"
        
        f"{E_SECTION_OPEN} {E_PERFORMANCE} {E_SECTION_CLOSE}  {bold('Performance')}\n"
        f"▸  <code>total</code> · {bold(total_checks_str)} {bold('checks')}\n"
        f"▸  <code>hits</code>  · {bold(hits_str)}\n"
        f"▸  <code>rank</code>  · {bold(rank_str)}\n\n"
        
        f"{E_STAR}  {bold('keep grinding  ·  hits matter')}"
    )
    
    await update.message.reply_text(text)

