"""
Plank — Inline keyboard builders.
"""

import re
from telegram import InlineKeyboardButton as TelegramInlineKeyboardButton, InlineKeyboardMarkup

CUSTOM_EMOJI_PATTERN = re.compile(r'<tg-emoji emoji-id="(\d+)">([^<]*)</tg-emoji>')

class InlineKeyboardButton(TelegramInlineKeyboardButton):
    def __init__(self, text: str, *args, **kwargs):
        text_str = str(text)
        match = CUSTOM_EMOJI_PATTERN.search(text_str)
        if match:
            emoji_id = match.group(1)
            clean_text = CUSTOM_EMOJI_PATTERN.sub("", text_str).strip()
            api_kwargs = kwargs.setdefault("api_kwargs", {})
            api_kwargs["icon_custom_emoji_id"] = emoji_id
            super().__init__(clean_text, *args, **kwargs)
        else:
            super().__init__(text, *args, **kwargs)


from config import CHAT_INVITE_LINK, CHANNEL_INVITE_LINK, CUSTOM_PLAN_CONTACT
from utils.emojis import (
    E_CHECK, E_STAR, E_DIAMOND, E_DOC, E_MONEY, E_CROSS, E_ERROR,
    E_STOP, E_RETRY, E_USER, E_CHART, E_GIFT, E_KEY, E_BAN,
    E_CHANNEL, E_GROUP, E_BROADCAST, E_CHAIN, get_emoji,
    E_JOIN_GROUP, E_JOIN_CHANNEL, E_HELP_GATES, E_HELP_TOOLS, E_HELP_CREDITS, E_HELP_ALL,
    E_HELP_PROFILE
)


def join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{E_CHANNEL} Join Channel", url=CHANNEL_INVITE_LINK,
                api_kwargs={"style": "primary"}
            ),
            InlineKeyboardButton(
                f"{E_GROUP} Join Group", url=CHAT_INVITE_LINK,
                api_kwargs={"style": "success"}
            ),
        ],
        [InlineKeyboardButton(
            f"{E_CHECK} Verify", callback_data="verify_join",
            api_kwargs={"style": "danger"}
        )],
    ])


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{E_HELP_GATES} Gates", callback_data="help_gates",
                api_kwargs={"style": "primary"}
            ),
            InlineKeyboardButton(
                f"{E_HELP_TOOLS} Tools", callback_data="help_tools",
                api_kwargs={"style": "success"}
            ),
        ],
        [
            InlineKeyboardButton(
                f"{E_HELP_CREDITS} Credits", callback_data="help_credits",
                api_kwargs={"style": "primary"}
            ),
            InlineKeyboardButton(
                f"{E_HELP_PROFILE} Profile", callback_data="help_profile",
                api_kwargs={"style": "success"}
            ),
        ],
        [
            InlineKeyboardButton(
                f"{E_HELP_ALL} All Commands", callback_data="help_all",
                api_kwargs={"style": "danger"}
            ),
        ]
    ])


def plans_keyboard() -> InlineKeyboardMarkup:
    cobble_emoji = get_emoji("cobblestone", "⚡️")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{cobble_emoji} Iron — $5/wk", callback_data="plan_cobblestone")],
        [InlineKeyboardButton(f"{E_STAR} Diamond — $15/mo", callback_data="plan_diamond")],
        [InlineKeyboardButton(f"{E_DIAMOND} Netherite — $30/mo", callback_data="plan_bedrock")],
        [InlineKeyboardButton(f"{E_DOC} Custom Plans — {CUSTOM_PLAN_CONTACT}", url=f"https://t.me/{CUSTOM_PLAN_CONTACT.lstrip('@')}")],
    ])


def mass_keyboard(session_id: str, approved: int = 0, charged: int = 0,
                   dead: int = 0, error: int = 0, stopped: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if charged > 0:
        rows.append([InlineKeyboardButton(f"{E_MONEY} Charged ({charged})", callback_data=f"mview_charged_{session_id}")])
    if approved > 0:
        rows.append([InlineKeyboardButton(f"{E_CHECK} Approved ({approved})", callback_data=f"mview_approved_{session_id}")])
    if dead > 0:
        rows.append([InlineKeyboardButton(f"{E_CROSS} Dead ({dead})", callback_data=f"mview_dead_{session_id}")])
    if error > 0:
        rows.append([InlineKeyboardButton(f"{E_ERROR} Error ({error})", callback_data=f"mview_error_{session_id}")])
    if not stopped:
        rows.append([InlineKeyboardButton(f"{E_STOP} Stop", callback_data=f"mstop_{session_id}")])
    else:
        if error > 0:
            rows.append([InlineKeyboardButton(f"{E_RETRY} Retry Errors", callback_data=f"mretry_{session_id}")])
    return InlineKeyboardMarkup(rows)


def sitechk_keyboard(session_id: str, fast: int = 0, slow: int = 0, invalid: int = 0,
                     error: int = 0, stopped: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if fast > 0:
        rows.append([InlineKeyboardButton(f"{E_CHECK} Fast ({fast})", callback_data=f"sview_fast_{session_id}")])
    if slow > 0:
        rows.append([InlineKeyboardButton(f"{E_CHECK} Slow ({slow})", callback_data=f"sview_slow_{session_id}")])
    if invalid > 0:
        rows.append([InlineKeyboardButton(f"{E_CROSS} Invalid ({invalid})", callback_data=f"sview_invalid_{session_id}")])
    if error > 0:
        rows.append([InlineKeyboardButton(f"{E_ERROR} Error ({error})", callback_data=f"sview_error_{session_id}")])
    if not stopped:
        rows.append([InlineKeyboardButton(f"{E_STOP} Stop", callback_data=f"sstop_{session_id}")])
    return InlineKeyboardMarkup(rows)


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{E_USER} Users", callback_data="admin_users"),
            InlineKeyboardButton(f"{E_CHART} Stats", callback_data="admin_stats"),
        ],
        [
            InlineKeyboardButton(f"{E_GIFT} Gen Codes", callback_data="admin_genplan"),
            InlineKeyboardButton(f"{E_KEY} Set Plan", callback_data="admin_setplan"),
        ],
        [
            InlineKeyboardButton(f"{E_MONEY} Add Credits", callback_data="admin_addcredits"),
            InlineKeyboardButton(f"{E_BAN} Ban/Unban", callback_data="admin_ban"),
        ],
        [
            InlineKeyboardButton(f"{E_BROADCAST} Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton(f"{E_CHAIN} Proxies", callback_data="admin_proxies"),
        ],
    ])

