"""
Plank — Emoji & styled-text helpers.
Loads custom emojis from emojis.json for easy customisation.
Uses Unicode bold/italic math-alphanumeric characters for the
aesthetic seen in premium Telegram bots.
"""

import json
import logging
import os

_EMOJI_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "emojis.json")

logger = logging.getLogger("Plank.emojis")

_emojis: dict = {}


def _load_emojis() -> dict:
    global _emojis
    if _emojis:
        return _emojis
    try:
        with open(_EMOJI_FILE, encoding="utf-8") as f:
            _emojis = json.load(f)
    except FileNotFoundError:
        _emojis = {}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse emojis.json: {e}")
        _emojis = {}
    return _emojis


def reload_emojis():
    """Force-reload emojis from disk (hot-reload support)."""
    global _emojis
    _emojis = {}
    _load_emojis()


def format_custom_emoji(val: any, fallback: str) -> str:
    if not val:
        return fallback
    
    if isinstance(val, dict):
        emoji_id = val.get("id")
        fallback_val = val.get("fallback", fallback)
        if emoji_id:
            return f'<tg-emoji emoji-id="{emoji_id}">{fallback_val}</tg-emoji>'
        return str(fallback_val)
        
    val_str = str(val).strip()
    if val_str.isdigit():
        return f'<tg-emoji emoji-id="{val_str}">{fallback}</tg-emoji>'
        
    if ":" in val_str:
        parts = val_str.split(":", 1)
        potential_id = parts[0].strip()
        potential_fallback = parts[1].strip()
        if potential_id.isdigit():
            return f'<tg-emoji emoji-id="{potential_id}">{potential_fallback}</tg-emoji>'
        
    if val_str.startswith("<tg-emoji"):
        if ' id="' in val_str:
            val_str = val_str.replace(' id="', ' emoji-id="', 1)
        return val_str
        
    return val_str


def get_emoji(name: str, fallback: str = "") -> str:
    val = _load_emojis().get(name, fallback)
    return format_custom_emoji(val, fallback)


class DynamicEmoji:
    def __init__(self, name: str, fallback: str):
        self._name = name
        self._fallback = fallback

    def _resolve(self) -> str:
        return get_emoji(self._name, self._fallback)

    def __str__(self) -> str:
        return self._resolve()

    def __repr__(self) -> str:
        return self._resolve()

    def __format__(self, format_spec) -> str:
        return self._resolve().__format__(format_spec)

    def __len__(self) -> int:
        return len(self._resolve())

    def __add__(self, other) -> str:
        return self._resolve() + str(other)

    def __radd__(self, other) -> str:
        return str(other) + self._resolve()

    def __eq__(self, other) -> bool:
        return self._resolve() == str(other)

    def __hash__(self) -> int:
        return hash(self._resolve())


# ── Section wrappers ──────────────────────────────────
def section(emoji: str, title: str, trail: str = "") -> str:
    so = get_emoji("section_open", "꒰")
    sc = get_emoji("section_close", "꒱")
    t = trail if trail else ""
    return f"{so} {emoji} {sc}  {bold(title)}{t}"


# ── Unicode bold sans-serif mapping ───────────────────
_BOLD_MAP = {}
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _BOLD_MAP[_c] = chr(0x1D5D4 + _i)
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _BOLD_MAP[_c] = chr(0x1D5EE + _i)
for _i, _c in enumerate("0123456789"):
    _BOLD_MAP[_c] = chr(0x1D7EC + _i)


def bold(text: str) -> str:
    return "".join(_BOLD_MAP.get(c, c) for c in text)


_ITALIC_MAP = {}
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"):
    if _i < 26:
        _ITALIC_MAP[_c] = chr(0x1D608 + _i)
    else:
        _ITALIC_MAP[_c] = chr(0x1D622 + (_i - 26))


def italic(text: str) -> str:
    return "".join(_ITALIC_MAP.get(c, c) for c in text)


# ── Common emoji shortcuts (loaded from emojis.json) ──
E_BOLT = DynamicEmoji("bolt", "⚡️")
E_STAR = DynamicEmoji("star", "⭐️")
E_MONEY = DynamicEmoji("money", "💰")
E_CHECK = DynamicEmoji("check", "✅")
E_CROSS = DynamicEmoji("cross", "❌")
E_WARN = DynamicEmoji("warn", "⚠️")
E_ERROR = DynamicEmoji("error", "⊖")
E_LOCK = DynamicEmoji("lock", "🔒")
E_BIN = DynamicEmoji("bin", "🔎")
E_CHAIN = DynamicEmoji("chain", "⛓️")
E_INFO = DynamicEmoji("info", "ℹ️")
E_FILE = DynamicEmoji("file", "📁")
E_DOC = DynamicEmoji("doc", "📄")
E_TOOLS = DynamicEmoji("tools", "⚙️")
E_CHART = DynamicEmoji("chart", "📊")
E_PC = DynamicEmoji("pc", "🖥")
E_CLOCK = DynamicEmoji("clock", "🕐")
E_DIAMOND = DynamicEmoji("diamond", "💎")
E_SHIELD = DynamicEmoji("shield", "🛡")
E_CROWN = DynamicEmoji("crown", "👑")
E_USER = DynamicEmoji("user", "👤")
E_GIFT = DynamicEmoji("gift", "🎁")
E_KEY = DynamicEmoji("key", "🔑")
E_FIRE = DynamicEmoji("fire", "🔥")
E_EARTH = DynamicEmoji("earth", "🌍")
E_ARROW = DynamicEmoji("arrow", "▸")
E_HEART = DynamicEmoji("heart", "♡")
E_PROGRESS_FILLED = DynamicEmoji("progress_filled", "●")
E_PROGRESS_EMPTY = DynamicEmoji("progress_empty", "○")
E_SPARKLE = DynamicEmoji("sparkle", "✦")
E_PAW = DynamicEmoji("paw", "🐾")
E_STOP = DynamicEmoji("stop", "⊖")
E_RETRY = DynamicEmoji("retry", "🔄")
E_BAN = DynamicEmoji("ban", "🚫")
E_CHANNEL = DynamicEmoji("channel", "📢")
E_GROUP = DynamicEmoji("group", "💬")
E_SPARKLES = DynamicEmoji("sparkles", "✨")
E_BROADCAST = DynamicEmoji("broadcast", "📢")
E_SECTION_OPEN = DynamicEmoji("section_open", "꒰")
E_SECTION_CLOSE = DynamicEmoji("section_close", "꒱")
E_DIRT = DynamicEmoji("dirt", "🟤")
E_COBBLESTONE = DynamicEmoji("cobblestone", "⚡️")
E_DIAMOND_PLAN = DynamicEmoji("diamond_plan", "⭐️")
E_BEDROCK = DynamicEmoji("bedrock", "💎")
E_SEPARATOR_CHAR = DynamicEmoji("separator_char", "♡")
E_MAINTENANCE = DynamicEmoji("maintenance", "🚧")
E_PACKAGE = DynamicEmoji("package", "📦")
E_WRENCH = DynamicEmoji("wrench", "🔧")
E_JOIN_GROUP = DynamicEmoji("join_group", "🔵")
E_JOIN_CHANNEL = DynamicEmoji("join_channel", "🔴")
E_HELP_GATES = DynamicEmoji("help_gates", "⚡️")
E_HELP_TOOLS = DynamicEmoji("help_tools", "⚙️")
E_HELP_CREDITS = DynamicEmoji("help_credits", "💰")
E_HELP_ALL = DynamicEmoji("help_all", "✨")
E_HELP_PROFILE = DynamicEmoji("help_profile", "👤")
E_PERFORMANCE = DynamicEmoji("performance", "📰")


# ── Separator ─────────────────────────────────────────
def separator(text: str = "") -> str:
    sep = get_emoji("separator_char", "─")
    if text:
        return f"<code>{sep * 3}</code>  {text}  <code>{sep * 3}</code>"
    return f"<code>{sep * 15}</code>"


def get_plan_emoji(plan_name: str) -> str:
    name = str(plan_name).lower().strip()
    if name == "dirt":
        return get_emoji("dirt", "🟤")
    elif name == "cobblestone":
        return get_emoji("cobblestone", "⚡️")
    elif name == "diamond":
        return get_emoji("diamond_plan", "⭐️")
    elif name == "bedrock":
        return get_emoji("bedrock", "💎")
    return "📦"


