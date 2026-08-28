import unittest
import os
import json
import asyncio
import time
from unittest.mock import patch, MagicMock, AsyncMock

# Overwrite database path for test isolation
import config
config.DATABASE_PATH = "test_plankbot.db"

import database
database.DATABASE_PATH = "test_plankbot.db"
database._local = type('', (), {})() # reset thread local connection for this test thread

from database import init_db, save_mass_session, get_mass_session
from utils.emojis import DynamicEmoji, get_emoji, reload_emojis, E_SECTION_OPEN, E_SECTION_CLOSE, get_plan_emoji
from utils.checkers import check_shopify, get_shopify_sites

class TestPlankBot(unittest.TestCase):
    def setUp(self):
        # Initialize test database
        if os.path.exists("test_plankbot.db"):
            os.remove("test_plankbot.db")
        init_db()
        self.original_sites_file = config.SHOPIFY_SITES_FILE
        config.SHOPIFY_SITES_FILE = "test_sites.txt"
        
        # Backup emojis.json
        self.emojis_backup = None
        if os.path.exists("emojis.json"):
            with open("emojis.json", "r", encoding="utf-8") as f:
                self.emojis_backup = f.read()

    def tearDown(self):
        # Close connection and clean up
        if hasattr(database._local, "conn") and database._local.conn:
            try:
                database._local.conn.close()
            except Exception:
                pass
            database._local.conn = None
        if os.path.exists("test_plankbot.db"):
            try:
                os.remove("test_plankbot.db")
            except Exception:
                pass
        config.SHOPIFY_SITES_FILE = self.original_sites_file
        if os.path.exists("test_sites.txt"):
            try:
                os.remove("test_sites.txt")
            except Exception:
                pass
        # Restore emojis.json backup
        if self.emojis_backup is not None:
            with open("emojis.json", "w", encoding="utf-8") as f:
                f.write(self.emojis_backup)
        elif os.path.exists("emojis.json"):
            try:
                os.remove("emojis.json")
            except Exception:
                pass
        reload_emojis()

    def test_dynamic_emojis(self):
        # Remove emojis.json to test defaults
        if os.path.exists("emojis.json"):
            os.remove("emojis.json")
        reload_emojis()
        
        # Test default emojis
        self.assertEqual(str(DynamicEmoji("stop", "⊖")), "⊖")
        self.assertEqual(str(DynamicEmoji("retry", "🔄")), "🔄")
        self.assertEqual(str(E_SECTION_OPEN), "꒰")
        self.assertEqual(str(E_SECTION_CLOSE), "꒱")
        self.assertEqual(get_plan_emoji("dirt"), "🟤")
        self.assertEqual(get_plan_emoji("cobblestone"), "⚡️")
        
        # Test override from emojis.json
        # Create a mock emojis.json file
        with open("emojis.json", "w", encoding="utf-8") as f:
            json.dump({
                "stop": "🛑",
                "retry": "♻️",
                "section_open": "「",
                "section_close": "」",
                "dirt": "💩"
            }, f)
        
        reload_emojis()
        self.assertEqual(str(DynamicEmoji("stop", "⊖")), "🛑")
        self.assertEqual(str(DynamicEmoji("retry", "🔄")), "♻️")
        self.assertEqual(str(E_SECTION_OPEN), "「")
        self.assertEqual(str(E_SECTION_CLOSE), "」")
        self.assertEqual(get_plan_emoji("dirt"), "💩")

    def test_custom_telegram_emoji_parsing(self):
        # 1. Test custom emoji rendering in DynamicEmoji when loaded from emojis.json
        # Mock emojis.json with digital strings, objects, and id:fallback format
        with open("emojis.json", "w", encoding="utf-8") as f:
            json.dump({
                "stop": "543210987654321",
                "retry": {"id": "987654321012345", "fallback": "🔄"},
                "ban": "<tg-emoji id=\"1111111111111\">🚫</tg-emoji>",
                "bolt": "999888777:⚡"
            }, f)
        
        reload_emojis()
        
        # stop: custom emoji ID represented as digit string
        self.assertEqual(str(DynamicEmoji("stop", "⊖")), '<tg-emoji emoji-id="543210987654321">⊖</tg-emoji>')
        
        # retry: custom emoji ID represented as dict
        self.assertEqual(str(DynamicEmoji("retry", "🔄")), '<tg-emoji emoji-id="987654321012345">🔄</tg-emoji>')
        
        # ban: custom emoji ID represented as raw HTML
        self.assertEqual(str(DynamicEmoji("ban", "🚫")), '<tg-emoji emoji-id="1111111111111">🚫</tg-emoji>')
        
        # bolt: custom emoji ID represented as id:fallback string
        self.assertEqual(str(DynamicEmoji("bolt", "⚡️")), '<tg-emoji emoji-id="999888777">⚡</tg-emoji>')
        
        # 2. Test InlineKeyboardButton subclass custom emoji extraction and button formatting
        from utils.keyboards import InlineKeyboardButton
        
        # Test custom emoji as digit string stopping
        btn_stop = InlineKeyboardButton(f"{DynamicEmoji('stop', '⊖')} Stop Process", callback_data="stop_data")
        serialized_stop = btn_stop.to_dict()
        self.assertEqual(serialized_stop["text"], "Stop Process")
        self.assertEqual(serialized_stop["icon_custom_emoji_id"], "543210987654321")
        
        # Test custom emoji as dict retry
        btn_retry = InlineKeyboardButton(f"{DynamicEmoji('retry', '🔄')} Retry Errors", callback_data="retry_data")
        serialized_retry = btn_retry.to_dict()
        self.assertEqual(serialized_retry["text"], "Retry Errors")
        self.assertEqual(serialized_retry["icon_custom_emoji_id"], "987654321012345")

        # Test normal unicode emoji button (no custom ID)
        btn_normal = InlineKeyboardButton("📢 Broadcast Message", callback_data="broadcast_data")
        serialized_normal = btn_normal.to_dict()
        self.assertEqual(serialized_normal["text"], "📢 Broadcast Message")
        self.assertNotIn("icon_custom_emoji_id", serialized_normal)

    def test_database_mass_sessions(self):
        # Create a dummy session state
        dummy_state = {
            "id": "test_session_123",
            "user_id": 99999,
            "username": "test_user",
            "gate": "shopify",
            "total": 10,
            "processed": 5,
            "charged": 1,
            "approved": 2,
            "dead": 2,
            "error": 0,
            "stopped": False,
            "site": "example.com",
            "workers": 5,
            "cooldown": 2.0,
            "last_active": 123456789.0,
            "msg_id": 5555,
            "chat_id": 6666,
            "checker_fn": lambda x: x,
            "cards": ["1111|12|28|111", "2222|12|28|222"],
            "results": {"error": [], "charged": ["1111"]},
            "user_proxies": ["http://proxy.com"]
        }
        
        save_mass_session(dummy_state)
        loaded = get_mass_session("test_session_123")
        
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["id"], "test_session_123")
        self.assertEqual(loaded["user_id"], 99999)
        self.assertEqual(loaded["username"], "test_user")
        self.assertEqual(loaded["gate"], "shopify")
        self.assertEqual(loaded["total"], 10)
        self.assertEqual(loaded["processed"], 5)
        self.assertEqual(loaded["charged"], 1)
        self.assertEqual(loaded["approved"], 2)
        self.assertEqual(loaded["dead"], 2)
        self.assertFalse(loaded["stopped"])
        self.assertEqual(loaded["site"], "example.com")
        self.assertEqual(loaded["workers"], 5)
        self.assertEqual(loaded["cooldown"], 2.0)
        self.assertEqual(loaded["msg_id"], 5555)
        self.assertEqual(loaded["chat_id"], 6666)
        
        # Test nonexistent session
        self.assertIsNone(get_mass_session("nonexistent"))

    def test_invalid_cvc_masking(self):
        # Mock client session and response
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"card_response": "INVALID_CVC", "price": "0.00", "gate": "Shopify Payments", "site": "example.com"})
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_resp
        mock_session.get.return_value = mock_cm
        
        with patch("utils.checkers._get_api_session", AsyncMock(return_value=mock_session)):
            res = asyncio.run(check_shopify("4111111111111111", "12", "2028", "123", site="example.com"))
        
        self.assertEqual(res["Response"], "3DS_REQUIRED")
        self.assertEqual(res["Approved"], "True")

    @patch("utils.checkers.get_shopify_sites")
    def test_product_over_main_retry_logic(self, mock_get_sites):
        # Configure sites
        mock_get_sites.return_value = ["site1.com", "site2.com", "site3.com", "site4.com", "site5.com", "site6.com"]
        
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"card_response": "PRODUCT_OVER_MAIN", "price": "0.00", "gate": "Shopify Payments", "site": "some-site.com"})
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_resp
        mock_session.get.return_value = mock_cm
        
        with patch("utils.checkers._get_api_session", AsyncMock(return_value=mock_session)):
            res = asyncio.run(check_shopify("4111111111111111", "12", "2028", "123", site="site1.com"))
        
        # Since we kept failing, it should have rotated across sites and finally returned "NO_PRODUCT"
        self.assertEqual(res["Response"], "NO_PRODUCT")
        
        # Check that it called get 3 times in total (1 initial + 2 retries)
        self.assertEqual(mock_session.get.call_count, 3)
        
        # Verify that all target sites were unique (site rotation)
        called_sites = []
        for call in mock_session.get.call_args_list:
            called_sites.append(call[1]["params"].get("site"))
        
        # The sites list contains unique sites
        self.assertEqual(len(set(called_sites)), 3)

    def test_new_api_responses_mapping(self):
        cases = [
            ("CHARGE_SUCCESS! ✅", "CHARGED", "True", "True"),
            ("3DS_SECURED! [Not charged] ❎", "3DS_REQUIRED", "False", "True"),
            ("INCORRECT_CVC!✅", "3DS_REQUIRED", "False", "True"),  # INVALID_CVC gets masked to 3DS_REQUIRED in check_shopify
            ("INSUFFICIENT FUNDS !✅", "INSUFFICIENT_FUNDS", "False", "True"),
            ("NO_PRODUCT: error detail", "NO_PRODUCT", "False", "False"),
            ("GENERIC_ERROR", "CARD_DECLINED", "False", "False"),
            ("PAYMENT_FAILED", "CARD_DECLINED", "False", "False"),
            ("PROCESSING_ERROR", "CARD_DECLINED", "False", "False"),
            ("SUBMIT_FAILED", "CARD_DECLINED", "False", "False"),
            ("SUBMIT_REJECTED", "CARD_DECLINED", "False", "False"),
            ("FAILED_RECEIPT", "CARD_DECLINED", "False", "False"),
            ("CART_FAILED", "API_ERROR", "False", "False"),
            ("TOKENIZATION_FAILED", "API_ERROR", "False", "False"),
            ("SITE_REQUIRES_LOGIN", "API_ERROR", "False", "False"),
            ("CHECKPOINTDENIED", "CARD_DECLINED", "False", "False"),
        ]
        
        for raw_resp, expected_resp, expected_charged, expected_approved in cases:
            mock_session = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={
                "card_response": raw_resp,
                "price": "0.00",
                "gate": "Shopify Payments",
                "site": "example.com"
            })
            
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_resp
            mock_session.get.return_value = mock_cm
            
            with patch("utils.checkers._get_api_session", AsyncMock(return_value=mock_session)):
                res = asyncio.run(check_shopify("4111111111111111", "12", "2028", "123", site="example.com"))
            
            self.assertEqual(res["Response"], expected_resp)
            self.assertEqual(res["Charged"], expected_charged)
            self.assertEqual(res["Approved"], expected_approved)

    def test_check_site_logic(self):
        from utils.checkers import check_site
        cases = [
            ("CARD_DECLINED", True, None),
            ("EXPIRED_CARD", False, None),
            ("CART_FAILED", False, "API_ERROR"),
            ("GENERIC_ERROR", True, None),
            ("CHARGE_SUCCESS! ✅", True, None),
        ]
        for raw_resp, expected_valid, expected_error in cases:
            mock_session = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={
                "Response": raw_resp,
                "price": "0.00",
                "gate": "Shopify Payments",
                "site": "example.com"
            })
            
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_resp
            mock_session.get.return_value = mock_cm
            
            with patch("utils.checkers._get_api_session", AsyncMock(return_value=mock_session)):
                res = asyncio.run(check_site("example.com"))
            
            self.assertEqual(res["valid"], expected_valid)
            self.assertEqual(res.get("error"), expected_error)


    def test_credits_unlimited_and_limited(self):
        from database import get_db, ensure_user, add_credits, deduct_credits, get_credits

        # Create a test user
        user_id = 12345
        ensure_user(user_id, "test_credits_user")

        # By default, users get plan default credits (500)
        self.assertEqual(get_credits(user_id), 500)

        # 1. Test normal deduction
        self.assertTrue(deduct_credits(user_id, 100))
        self.assertEqual(get_credits(user_id), 400)

        # 2. Test deduction when not enough credits
        self.assertFalse(deduct_credits(user_id, 500))
        self.assertEqual(get_credits(user_id), 400)

        # 3. Test normal add
        add_credits(user_id, 200)
        self.assertEqual(get_credits(user_id), 600)

        # 4. Make user unlimited (-1 credits)
        with get_db() as db:
            db.execute("UPDATE users SET credits = -1 WHERE user_id = ?", (user_id,))
        self.assertEqual(get_credits(user_id), -1)

        # 5. Test deduct with unlimited credits (should return True and credits remain -1)
        self.assertTrue(deduct_credits(user_id, 5000))
        self.assertEqual(get_credits(user_id), -1)

        # 6. Test add with unlimited credits (should do nothing and credits remain -1)
        add_credits(user_id, 1000)
        self.assertEqual(get_credits(user_id), -1)

    def test_priority_checking(self):
        from utils.checkers import register_priority_check_start, register_priority_check_end, check_shopify
        import utils.checkers
        
        # Test basic start/end registration
        self.assertEqual(utils.checkers._active_priority_checks, 0)
        register_priority_check_start()
        self.assertEqual(utils.checkers._active_priority_checks, 1)
        register_priority_check_end()
        self.assertEqual(utils.checkers._active_priority_checks, 0)

        # Mock API session for check_shopify
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"card_response": "CARD_DECLINED", "price": "0.00", "gate": "Shopify", "site": "example.com"})
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_resp
        mock_session.get.return_value = mock_cm
        
        with patch("utils.checkers._get_api_session", AsyncMock(return_value=mock_session)):
            # Calling priority check should increment counter during execution and decrement it after
            res = asyncio.run(check_shopify("4111111111111111", "12", "2028", "123", site="example.com", is_priority=True))
            self.assertEqual(utils.checkers._active_priority_checks, 0)
            
            # Non-priority check should run fine when no priority checks are active
            res2 = asyncio.run(check_shopify("4111111111111111", "12", "2028", "123", site="example.com", is_priority=False))
            self.assertEqual(utils.checkers._active_priority_checks, 0)

    def test_backup_command(self):
        from handlers.admin import backup_cmd
        from utils.emojis import E_PACKAGE
        from unittest.mock import AsyncMock, MagicMock
        import io
        import zipfile

        update = MagicMock()
        update.message = AsyncMock()
        
        # Mock owner check to return True
        with patch("handlers.admin._owner_check", return_value=True):
            context = MagicMock()
            
            # The backup_cmd sends status_msg, deletes it, and replies with document
            status_msg = AsyncMock()
            update.message.reply_text.return_value = status_msg
            
            # Call backup_cmd
            asyncio.run(backup_cmd(update, context))
            
            # Check status message was prepared
            update.message.reply_text.assert_called_with(f"{E_PACKAGE} Preparing backup of all source files...")
            
            # Check status message was deleted
            status_msg.delete.assert_called_once()
            
            # Check reply_document was called
            update.message.reply_document.assert_called_once()
            
            # Retrieve the zip file sent as document
            called_args, called_kwargs = update.message.reply_document.call_args
            sent_document = called_kwargs.get("document")
            
            # Ensure it is a valid zip containing python files
            self.assertIsNotNone(sent_document)
            self.assertTrue(isinstance(sent_document, io.BytesIO))
            
            with zipfile.ZipFile(sent_document, "r") as zip_file:
                file_list = zip_file.namelist()
                # Should contain files like config.py, database.py, bot.py, etc.
                self.assertIn("config.py", file_list)
                self.assertIn("database.py", file_list)
                self.assertIn("bot.py", file_list)

    def test_card_categorization(self):
        from handlers.gates import _categorize
        
        # Test EXPIRED_CARD is categorized as dead, not approved
        self.assertEqual(_categorize("EXPIRED_CARD"), "dead")
        self.assertEqual(_categorize("expired_card"), "dead")
        
        # Test other categories
        self.assertEqual(_categorize("CHARGED"), "charged")
        self.assertEqual(_categorize("ORDER_PLACED"), "charged")
        self.assertEqual(_categorize("3DS_REQUIRED"), "approved")
        self.assertEqual(_categorize("INSUFFICIENT_FUNDS"), "approved")
        self.assertEqual(_categorize("INVALID_CVC"), "approved")
        self.assertEqual(_categorize("LIMIT_EXCEEDED"), "approved")
        self.assertEqual(_categorize("TIMEOUT"), "error")
        self.assertEqual(_categorize("SOME_UNKNOWN_RESPONSE"), "dead")

    def test_siterem_command(self):
        from handlers.admin import siterem_cmd, _load_sites, _save_sites
        update = MagicMock()
        update.message = AsyncMock()
        
        # Setup initial sites list
        _save_sites(["kyliebaby.com", "gymshark.com"])
        
        with patch("handlers.admin._owner_check", return_value=True):
            context = MagicMock()
            context.args = ["gymshark.com"]
            
            # Call siterem_cmd
            asyncio.run(siterem_cmd(update, context))
            
            # Verify the site was removed
            remaining = _load_sites()
            self.assertEqual(remaining, ["kyliebaby.com"])
            
            # Test removing non-existent site
            context.args = ["nonexistent.com"]
            asyncio.run(siterem_cmd(update, context))
            
            # Test with no arguments
            context.args = []
            asyncio.run(siterem_cmd(update, context))

    def test_debug_command(self):
        from handlers.admin import debug_cmd
        from config import OWNER_DEBUG_MODE
        update = MagicMock()
        update.effective_user.id = 6636230545
        update.message = AsyncMock()
        
        # Initially debug mode is off
        OWNER_DEBUG_MODE[6636230545] = False
        
        with patch("handlers.admin._owner_check", return_value=True):
            context = MagicMock()
            
            # Toggle debug mode
            asyncio.run(debug_cmd(update, context))
            self.assertTrue(OWNER_DEBUG_MODE[6636230545])
            
            # Toggle it off
            asyncio.run(debug_cmd(update, context))
            self.assertFalse(OWNER_DEBUG_MODE[6636230545])

    def test_debug_info(self):
        print("\n=== DEBUG: DATABASE INFO ===")
        import sqlite3
        conn = sqlite3.connect("plankbot.db")
        conn.row_factory = sqlite3.Row
        for uid in (7167704900, 6636230545):
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
            if row:
                print(f"User {uid}: Plan: {row['plan']}, Credits: {row['credits']}, Banned: {row['banned']}")
            else:
                print(f"User {uid} not found")
        
        print("\n=== DEBUG: DIFF WITH BACKUP ===")
        import zipfile
        import difflib
        with zipfile.ZipFile("plankbot_backup.zip") as z:
            orig = z.read("handlers/gates.py").decode("utf-8")
        with open("handlers/gates.py") as f:
            curr = f.read()
        diff = list(difflib.unified_diff(orig.splitlines(), curr.splitlines(), fromfile="backup", tofile="current"))
        print("\n".join(diff[:50]))
        self.fail("Show debug output")

if __name__ == "__main__":
    unittest.main()
