"""
Plank — /start handler and join-check middleware.
"""

from telegram import Update
from telegram.ext import ContextTypes

from config import PLANS, BRAND_NAME, CUSTOM_PLAN_CONTACT
from database import ensure_user, run_in_db
from utils.emojis import section, bold, separator, E_BOLT, E_STAR, E_MONEY, E_TOOLS, E_ARROW, E_HEART, E_SPARKLE, get_emoji, get_plan_emoji
from utils.helpers import check_membership
from utils.keyboards import join_keyboard, plans_keyboard


async def membership_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if user passes membership check, False otherwise."""
    user = update.effective_user
    if not user:
        return False

    in_chat, in_channel = await check_membership(context.bot, user.id)
    if in_chat and in_channel:
        return True

    parts = [f"{section(E_BOLT, 'Join Required')}\n"]
    if not in_channel:
        parts.append(f"   {E_ARROW} Join our {bold('channel')} first")
    if not in_chat:
        parts.append(f"   {E_ARROW} Join our {bold('group')} first")
    parts.append(f"\n{separator(f'{BRAND_NAME}')}")

    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if msg:
        await msg.reply_text("\n".join(parts), reply_markup=join_keyboard())
    return False


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await run_in_db(ensure_user, user.id, user.username or "")

    if not await membership_guard(update, context):
        return

    text = (
        f"{section(E_SPARKLE, BRAND_NAME)}\n\n"
        f"╰ premium checker bot\n"
        f"╰ type /help for cmds\n"
    )
    await update.message.reply_text(text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    text = (
        f"{section(E_BOLT, 'Gates')}\n"
        f"╰ /sh · shopify  │  /msh · mass\n\n"
        f"{section(E_TOOLS, 'Tools')}\n"
        f"╰ /vbv /mvbv · 3ds check\n"
        f"╰ /bin · lookup  │  /proxy · manage\n"
        f"╰ /split · split  │  /genad · addr\n"
        f"╰ /scr · scrape cards\n\n"
        f"{section(E_MONEY, 'Credits')}\n"
        f"╰ /daily /balance /redeem /plans\n"
    )
    await update.message.reply_text(text)


async def plans_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await membership_guard(update, context):
        return

    lines = [f"{section(E_MONEY, 'Plans')}\n"]
    for key, p in PLANS.items():
        if key == "dirt":
            continue
        credits_str = f"{p['credits']:,}"
        plan_emoji = get_plan_emoji(key)
        lines.append(
            f"{section(plan_emoji, p['display'], ' · ' + p.get('price'))}\n"
            f"╰ {p['workers']}w · {credits_str}cr · {p['cooldown']}s cd\n"
        )

    lines.append(f"╰ custom plans → {bold(CUSTOM_PLAN_CONTACT)}\n")

    await update.message.reply_text("\n".join(lines), reply_markup=plans_keyboard())


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    user = query.from_user

    # Clear membership cache entry to force recheck
    from utils.helpers import _membership_cache
    _membership_cache.pop(user.id, None)

    in_chat, in_channel = await check_membership(context.bot, user.id)
    if in_chat and in_channel:
        await run_in_db(ensure_user, user.id, user.username or "")
        await query.edit_message_text(
            f"{section(E_SPARKLE, 'Verified')}"
            f"\n\n╰ welcome, @{user.username or user.first_name}"
            f"\n╰ type /help to begin\n"
        )
    else:
        try:
            await query.answer("join both group & channel first", show_alert=True)
        except Exception:
            pass


async def plans_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plan button clicks — show plan details and how to subscribe."""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    plan_key = query.data.replace("plan_", "")
    plan = PLANS.get(plan_key)
    if not plan:
        return

    credits_str = f"{plan['credits']:,}"

    display = plan['display']
    price = plan['price']
    plan_emoji = get_plan_emoji(plan_key)
    text = (
        f"{section(plan_emoji, display, f' · {price}')}\n\n"
        f"╰ workers  · {bold(str(plan['workers']) + 'w')}\n"
        f"╰ credits  · {bold(credits_str)}\n"
        f"╰ cooldown · {bold(str(plan['cooldown']) + 's')}\n"
        f"╰ mass     · {bold(str(plan['mass_limit']))}\n"
        f"╰ daily    · +{bold(str(plan['daily_bonus']))}\n\n"
        f"╰ contact {bold(CUSTOM_PLAN_CONTACT)} or /redeem\n"
    )
    await query.message.reply_text(text)
