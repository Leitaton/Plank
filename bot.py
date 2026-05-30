"""
Plank — Main entry point.
Advanced Telegram bot with credit system, Shopify gate, tools, and admin panel.
Designed to handle 400-500+ concurrent members.
"""

import logging

from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    TypeHandler,
    filters,
    Defaults,
    ContextTypes,
    AIORateLimiter,
)
from telegram.ext import ApplicationHandlerStop

from config import BOT_TOKEN
from database import init_db

from handlers.start import start_cmd, help_cmd, plans_cmd, verify_callback, plans_callback
from handlers.credits import daily_cmd, balance_cmd, redeem_cmd
from handlers.gates import (
    sh_cmd, msh_cmd,
    mass_stop_callback, mass_view_callback, mass_retry_callback,
)
from handlers.tools import (
    vbv_cmd, mvbv_cmd, bin_cmd, proxy_cmd,
    split_cmd, genad_cmd, scr_cmd,
)
from handlers.admin import (
    admin_help_cmd, genplan_cmd, setplan_cmd, addcredits_cmd,
    ban_cmd, unban_cmd, userinfo_cmd, stats_cmd,
    broadcast_cmd, allusers_cmd, admin_callback, site_cmd,
    sitechk_cmd, siteclean_cmd, siteadd_cmd, sitetest_cmd, sitecard_cmd, 
    sitechk_callback, reload_cmd,
    backup_cmd, maintenance_cmd,
)

from utils.helpers import is_owner
import os

async def maintenance_middleware(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Intercept all updates if maintenance is active and user is not owner."""
    if not os.path.exists("maintenance.flag"):
        return
    
    # Try to get user_id from update
    user_id = None
    if getattr(update, "message", None) and update.message.from_user:
        user_id = update.message.from_user.id
    elif getattr(update, "callback_query", None) and update.callback_query.from_user:
        user_id = update.callback_query.from_user.id

    if user_id and is_owner(user_id):
        return # Let owners through

    # Tell the user if it's a message containing a command
    if getattr(update, "message", None):
        msg = update.message
        if msg.text and msg.text.startswith("/"):
            command = msg.text.split()[0].lower()
            should_reply = True
            
            # If the command has an @ tag, ensure it's for this bot
            if "@" in command:
                cmd_base, target_bot = command.split("@", 1)
                if context.bot.username and target_bot != context.bot.username.lower():
                    should_reply = False
                command = cmd_base # remove the @bot part for whitelist checking
            
            # Whitelist of PlankBot's commands
            VALID_COMMANDS = {
                "/start", "/help", "/plans", "/daily", "/balance", "/redeem", 
                "/sh", "/msh", "/vbv", "/mvbv", "/bin", "/proxy", "/split", 
                "/genad", "/scr", "/admin", "/admin_help", "/genplan", 
                "/setplan", "/addcredits", "/ban", "/unban", "/userinfo", 
                "/stats", "/broadcast", "/allusers", "/site", "/sitechk", 
                "/siteclean", "/siteadd", "/sitetest", "/sitecard", "/maintenance", 
                "/reload", "/backup"
            }
            
            if command not in VALID_COMMANDS:
                should_reply = False
            
            if should_reply:
                try:
                    await msg.reply_text("🚧 **Bot is under maintenance.** Please try again later.", parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    pass
    elif getattr(update, "callback_query", None):
        try:
            await update.callback_query.answer("Bot is under maintenance.", show_alert=True)
        except Exception:
            pass
    
    raise ApplicationHandlerStop()

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("Plank")

# Silence noisy HTTP request logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.ExtBot").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._application").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler to gracefully log NetworkError (e.g. Bad Gateway) and other exceptions."""
    from telegram.error import NetworkError
    if isinstance(context.error, NetworkError):
        logger.warning(f"Telegram NetworkError encountered: {context.error}")
    else:
        logger.exception("Exception while handling an update:", exc_info=context.error)


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set. Export it or add to .env")
        return

    init_db()
    logger.info("Database initialised.")

    defaults = Defaults(parse_mode=ParseMode.HTML)

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .defaults(defaults)
        .concurrent_updates(True)
        .connection_pool_size(256)
        .pool_timeout(60)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(60)
        .rate_limiter(AIORateLimiter(max_retries=30))
        .build()
    )

    # ── Core commands ─────────────────────────────────
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("plans", plans_cmd))

    # ── Credit commands ───────────────────────────────
    app.add_handler(CommandHandler("daily", daily_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))

    # ── Gate commands ─────────────────────────────────
    app.add_handler(CommandHandler("sh", sh_cmd))
    app.add_handler(CommandHandler("msh", msh_cmd))

    # ── Tool commands ─────────────────────────────────
    app.add_handler(CommandHandler("vbv", vbv_cmd))
    app.add_handler(CommandHandler("mvbv", mvbv_cmd))
    app.add_handler(CommandHandler("bin", bin_cmd))
    app.add_handler(CommandHandler("proxy", proxy_cmd))
    app.add_handler(CommandHandler("split", split_cmd))
    app.add_handler(CommandHandler("genad", genad_cmd))
    app.add_handler(CommandHandler("scr", scr_cmd))

    # ── Admin commands ────────────────────────────────
    app.add_handler(CommandHandler("admin", admin_help_cmd))
    app.add_handler(CommandHandler("admin_help", admin_help_cmd))
    app.add_handler(CommandHandler("genplan", genplan_cmd))
    app.add_handler(CommandHandler("setplan", setplan_cmd))
    app.add_handler(CommandHandler("addcredits", addcredits_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("userinfo", userinfo_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("allusers", allusers_cmd))
    app.add_handler(CommandHandler("site", site_cmd))
    app.add_handler(CommandHandler("sitechk", sitechk_cmd))
    app.add_handler(CommandHandler("siteclean", siteclean_cmd))
    app.add_handler(CommandHandler("siteadd", siteadd_cmd))
    app.add_handler(CommandHandler("sitetest", sitetest_cmd))
    app.add_handler(CommandHandler("sitecard", sitecard_cmd))
    app.add_handler(CommandHandler("maintenance", maintenance_cmd))
    app.add_handler(CommandHandler("reload", reload_cmd))
    app.add_handler(CommandHandler("backup", backup_cmd))

    # ── Callback queries ──────────────────────────────
    app.add_handler(CallbackQueryHandler(verify_callback, pattern=r"^verify_join$"))
    app.add_handler(CallbackQueryHandler(mass_stop_callback, pattern=r"^mstop_"))
    app.add_handler(CallbackQueryHandler(mass_view_callback, pattern=r"^mview_"))
    app.add_handler(CallbackQueryHandler(plans_callback, pattern=r"^plan_"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin_"))
    app.add_handler(CallbackQueryHandler(mass_retry_callback, pattern=r"^mretry_"))
    app.add_handler(CallbackQueryHandler(sitechk_callback, pattern=r"^sview_|^sstop_"))

    # ── File handler for mass commands via document ───
    app.add_handler(MessageHandler(
        filters.Document.FileExtension("txt") & filters.CaptionRegex(r"^/(msh|mvbv|split)"),
        _route_document,
    ))

    app.add_error_handler(error_handler)

    # Add maintenance middleware to run before anything else
    app.add_handler(TypeHandler(object, maintenance_middleware), group=-1)

    logger.info("Plank starting...")
    app.run_polling(drop_pending_updates=True, allowed_updates=["message", "callback_query"])


async def _route_document(update, context):
    caption = (update.message.caption or "").strip()
    if caption.startswith("/msh"):
        await msh_cmd(update, context)
    elif caption.startswith("/mvbv"):
        await mvbv_cmd(update, context)
    elif caption.startswith("/split"):
        await split_cmd(update, context)


if __name__ == "__main__":
    main()
