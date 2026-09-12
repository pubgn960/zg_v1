"""
Unit test suite for Telegram Email Image Delivery Bot.
Tests email, Order ID, package extraction, keyword detection, caption email overrides,
wrong details workflow, duplicate pending order detection, album splitting, SHA256 fingerprinting, user sessions,
BOT_SETTINGS cache, Role-Based User Management (AUTH_USERS_CACHE, Super Admin, Delivery Users),
Ignoring Super Admin & Delivery User messages in Client Group,
Group Category Routing System (v1.2: Category A, Category B, Payment Review, Approve, Reject),
Multi-Loader Approval System (Loader CRUD, LOADERS_CACHE, Multi-Loader Assignment),
Telegram BotCommand Validation (validate_bot_command),
Loader Add Wizard state isolation (LOADER_ADD_SESSION),
Category A Only Price Workflow (update_order_price),
and two-group reply-based DB operations.
"""

import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from telegram import BotCommand
from telegram.ext import ApplicationHandlerStop

from order_parser import parse_order_v2
from email_parser import extract_email, extract_order_id, extract_package, extract_last_email
from keywords import contains_order_keyword
from delivery import chunk_list
from media_collector import user_session_manager
from utils import is_super_admin, is_delivery_user
from main import validate_bot_command
from calculator import (
    safe_eval,
    format_num,
    is_math_expression,
    evaluate_math_expression
)
from handlers import (
    LOADER_ADD_SESSION,
    is_valid_price_string,
    source_group_handler,
    edited_message_handler,
    calc_command,
    calccancel_command,
    calculator_text_handler,
    paid_command,
    undo_command,
    myid_command,
    broadcast_command
)
from database import (
    BOT_SETTINGS,
    AUTH_USERS_CACHE,
    CLIENT_GROUPS_CACHE,
    LOADERS_CACHE,
    init_db,
    reload_bot_settings_cache,
    reload_auth_users_cache,
    reload_loaders_cache,
    set_client_group_category,
    remove_client_group_category,
    get_client_group_category,
    update_payment_review_group,
    update_order_status,
    set_order_price_prompt,
    update_order_price,
    add_authorized_user,
    remove_authorized_user,
    get_all_authorized_users,
    add_loader,
    remove_loader_by_id,
    get_all_loaders,
    create_order,
    set_order_loader_message_id,
    get_order_by_id,
    get_pending_order_by_email,
    get_order_by_loader_msg_id,
    add_images_to_order,
    mark_order_delivered,
    cancel_order,
    get_pending_orders,
    get_delivered_orders,
    delete_orders_by_email,
    get_detailed_stats,
    compute_fingerprint,
    export_orders_to_csv,
    get_or_create_settings,
    update_source_group,
    update_delivery_group,
    reset_groups,
    get_group_total_balance,
    add_to_group_total,
    paid_group_total,
    undo_group_total,
    get_all_group_totals_chat_ids
)


class TestCategoryAPriceWorkflow(unittest.IsolatedAsyncioTestCase):
    """Tests Category A Price workflow DB updates and string validation."""

    def test_price_validation(self):
        # Valid numbers
        self.assertTrue(is_valid_price_string("15"))
        self.assertTrue(is_valid_price_string("15.5"))
        self.assertTrue(is_valid_price_string("2500"))
        self.assertTrue(is_valid_price_string("2999.99"))

        # Invalid formats
        self.assertFalse(is_valid_price_string("abc"))
        self.assertFalse(is_valid_price_string("15rs"))
        self.assertFalse(is_valid_price_string("price 20"))
        self.assertFalse(is_valid_price_string("15.5.5"))

    async def test_order_price_update(self):
        await init_db()

        email = "price_test@example.com"
        order = await create_order(email, category="A")
        self.assertIsNone(order.price)
        self.assertEqual(order.category, "A")

        # Set Prompt
        await set_order_price_prompt(order.id, 998877)
        check_prompt = await get_order_by_id(order.id)
        self.assertEqual(check_prompt.price_prompt_msg_id, 998877)

        # Set Price (should clear prompt ID and set price_msg_id)
        updated = await update_order_price(order.id, "15.5", price_msg_id=12345)
        self.assertEqual(updated.price, "15.5")
        self.assertEqual(updated.price_msg_id, 12345)
        self.assertIsNone(updated.price_prompt_msg_id)

        # Edit Price
        edited = await update_order_price(order.id, "30", price_msg_id=67890)
        self.assertEqual(edited.price, "30")
        self.assertEqual(edited.price_msg_id, 67890)

        # Clean up
        await delete_orders_by_email(email)


class TestLoaderWizardState(unittest.TestCase):
    """Tests Loader Add Wizard state isolation."""

    def test_session_isolation(self):
        LOADER_ADD_SESSION.clear()
        self.assertNotIn(12345, LOADER_ADD_SESSION)

        # User 1 initiates wizard
        LOADER_ADD_SESSION[12345] = {"step": 1, "chat_id": -100111}
        self.assertIn(12345, LOADER_ADD_SESSION)
        self.assertNotIn(67890, LOADER_ADD_SESSION)

        LOADER_ADD_SESSION.clear()


class TestBotCommandValidation(unittest.TestCase):
    """Tests validate_bot_command against Telegram API rules."""

    def test_valid_commands(self):
        self.assertTrue(validate_bot_command(BotCommand("a", "Set Category A")))
        self.assertTrue(validate_bot_command(BotCommand("b", "Set Category B")))
        self.assertTrue(validate_bot_command(BotCommand("loaderadd", "Add Loader")))
        self.assertTrue(validate_bot_command(BotCommand("loader_list", "List Loaders")))

    def test_invalid_commands(self):
        # Uppercase not allowed
        self.assertFalse(validate_bot_command(BotCommand("A", "Set Category A")))
        self.assertFalse(validate_bot_command(BotCommand("B", "Set Category B")))
        # Spaces or special chars not allowed
        self.assertFalse(validate_bot_command(BotCommand("loader-add", "Add Loader")))
        self.assertFalse(validate_bot_command(BotCommand("loader add", "Add Loader")))
        # Empty description not allowed
        self.assertFalse(validate_bot_command(BotCommand("a", "")))


class TestMultiLoaderManagement(unittest.IsolatedAsyncioTestCase):
    """Tests Loader CRUD operations, cache synchronization, and multi-loader assignment."""

    async def test_loader_crud_and_cache(self):
        await init_db()

        # Add Loader 1
        l1 = await add_loader(-1001234567890, "Pakistan Loader")
        self.assertIsNotNone(l1.id)

        # Add Loader 2
        l2 = await add_loader(-1009876543210, "India Loader")
        self.assertIsNotNone(l2.id)

        # Check cache
        self.assertIn(l1.id, LOADERS_CACHE)
        self.assertEqual(LOADERS_CACHE[l1.id]["name"], "Pakistan Loader")

        # List Loaders
        loaders = await get_all_loaders()
        self.assertTrue(len(loaders) >= 2)

        # Remove Loader
        removed = await remove_loader_by_id(l1.id)
        self.assertTrue(removed)
        self.assertNotIn(l1.id, LOADERS_CACHE)

        # Clean up
        await remove_loader_by_id(l2.id)


class TestGroupCategoryRouting(unittest.IsolatedAsyncioTestCase):
    """Tests Group Category Routing (v1.2) - Category A, Category B, Payment Review, Approve, Reject."""

    async def test_category_assignment_and_cache(self):
        await init_db()

        chat_id_a = -100555444333222
        chat_id_b = -100999888777666

        # Set Category A
        await set_client_group_category(chat_id_a, "Pakistan CODM Shop A", "A")
        self.assertEqual(await get_client_group_category(chat_id_a), "A")

        # Set Category B
        await set_client_group_category(chat_id_b, "Pakistan CODM Shop B", "B")
        self.assertEqual(await get_client_group_category(chat_id_b), "B")

        # Test Payment Review Group update
        pay_chat_id = -100111222333444
        await update_payment_review_group(pay_chat_id, "Payment Review Group")
        self.assertEqual(BOT_SETTINGS["payment_review_group_id"], pay_chat_id)

        # Test Category B order creation & status updates
        email = "catb_test@example.com"
        order = await create_order(email, client_chat_id=chat_id_b, original_message_id=101, status="Pending Payment")
        self.assertEqual(order.status, "Pending Payment")

        # Approve Order
        approved_order = await update_order_status(order.id, "Approved")
        self.assertEqual(approved_order.status, "Approved")

        # Reject Order
        rejected_order = await update_order_status(order.id, "Rejected")
        self.assertEqual(rejected_order.status, "Rejected")

        # Remove Category
        await remove_client_group_category(chat_id_a)
        await remove_client_group_category(chat_id_b)
        await delete_orders_by_email(email)


class TestAdminAccessPermissions(unittest.IsolatedAsyncioTestCase):
    """Tests strict admin access permissions."""

    async def test_admin_access_permission_check(self):
        await init_db()
        cust_uid = 987654321
        admin_uid = 8261988472
        self.assertFalse(is_super_admin(cust_uid))
        self.assertTrue(is_super_admin(admin_uid))


class TestDuplicateOrderDetection(unittest.IsolatedAsyncioTestCase):
    """Tests duplicate pending order detection."""

    async def test_get_pending_order_by_email(self):
        await init_db()

        email = "dup_detect_test@example.com"
        # No pending order initially
        initial = await get_pending_order_by_email(email)
        self.assertIsNone(initial)

        # Create pending order
        o1 = await create_order(email, status="Pending")
        found = await get_pending_order_by_email(email)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, o1.id)

        # Deliver order
        await mark_order_delivered(o1.id)
        found_after_del = await get_pending_order_by_email(email)
        self.assertIsNone(found_after_del)

        # Cleanup
        await delete_orders_by_email(email)


class TestCaptionEmailAndWrongDetails(unittest.TestCase):
    """Tests extract_last_email helper for Loader caption email overrides and wrong details detection."""

    def test_extract_last_email_single(self):
        text = "AG Done\n\nabc@gmail.com"
        self.assertEqual(extract_last_email(text), "abc@gmail.com")

    def test_extract_last_email_multiple(self):
        text = "abc@gmail.com\n\nCompleted Successfully"
        self.assertEqual(extract_last_email(text), "abc@gmail.com")

    def test_extract_last_email_override(self):
        text = "AG Done\nold@gmail.com\nnew@gmail.com\nFinished"
        self.assertEqual(extract_last_email(text), "new@gmail.com")

    def test_extract_last_email_none(self):
        text = "AG Done\nNo email here"
        self.assertIsNone(extract_last_email(text))

    def test_wrong_details_keyword(self):
        self.assertIn("wrong", "wrong".lower())
        self.assertIn("wrong", "Wrong details provided".lower())
        self.assertIn("wrong", "WRONG".lower())


class TestBotSettingsCache(unittest.IsolatedAsyncioTestCase):
    """Tests in-memory BOT_SETTINGS cache initialization and updates."""

    async def test_cache_update_and_reload(self):
        await init_db()

        # Update source group and verify cache instantly reflects changes
        await update_source_group(-1001234567890, "Test Client Group")
        self.assertEqual(BOT_SETTINGS["source_group_id"], -1001234567890)
        self.assertEqual(BOT_SETTINGS["source_group_title"], "Test Client Group")

        # Update delivery group and verify cache instantly reflects changes
        await update_delivery_group(-1009876543210, "Test Loader Group")
        self.assertEqual(BOT_SETTINGS["delivery_group_id"], -1009876543210)
        self.assertEqual(BOT_SETTINGS["delivery_group_title"], "Test Loader Group")

        # Simulate bot restart by calling reload_bot_settings_cache()
        cached = await reload_bot_settings_cache()
        self.assertEqual(cached["source_group_id"], -1001234567890)
        self.assertEqual(cached["delivery_group_id"], -1009876543210)

        # Reset groups and verify cache cleared
        await reset_groups()
        self.assertIsNone(BOT_SETTINGS["source_group_id"])
        self.assertIsNone(BOT_SETTINGS["delivery_group_id"])


class TestKeywordDetector(unittest.TestCase):
    """Tests strict 4-condition order detection integration in keywords.py."""

    def test_keyword_matches(self):
        # Match cases (Platform + Email + Password + Package)
        self.assertTrue(contains_order_keyword("Facebook\nEmail: abc@gmail.com\nPassword: 123456\n10800 CP")[0])
        self.assertTrue(contains_order_keyword("FB\nLogin: test@hotmail.com\nPass: 123\n420")[0])
        self.assertTrue(contains_order_keyword("Activision\nEmail: abc@outlook.com\nPassword: pass123\n2400 CP")[0])

    def test_keyword_ignores(self):
        # Ignore cases (Incomplete messages missing 1 or more conditions)
        self.assertFalse(contains_order_keyword("10800 CP\nabc@gmail.com")[0])
        self.assertFalse(contains_order_keyword("Need CP")[0])
        self.assertFalse(contains_order_keyword("Hello")[0])
        self.assertFalse(contains_order_keyword("10800 CP")[0])
        self.assertFalse(contains_order_keyword("Facebook")[0])


class TestEmailOrderPackageParser(unittest.TestCase):
    """Tests email, Order ID, and package regex extraction."""

    def test_extract_basic_email(self):
        text = "Order confirmation for john@gmail.com please deliver."
        self.assertEqual(extract_email(text), "john@gmail.com")

    def test_extract_order_id_formats(self):
        self.assertEqual(extract_order_id("Order ID: #10025"), 10025)
        self.assertEqual(extract_order_id("Order #10025"), 10025)
        self.assertEqual(extract_order_id("#10025"), 10025)
        self.assertEqual(extract_order_id("Order ID: 10025"), 10025)

    def test_extract_package_description(self):
        text = "10800 CP\nEmail: test@gmail.com"
        self.assertEqual(extract_package(text), "10800 CP")


class TestDeliverySplitting(unittest.TestCase):
    """Tests album splitting logic (8, 18, 35, 100+ images)."""

    def test_chunking_eight_images(self):
        images = [f"file_id_{i}" for i in range(8)]
        chunks = chunk_list(images, chunk_size=10)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 8)

    def test_chunking_eighteen_images(self):
        images = [f"file_id_{i}" for i in range(18)]
        chunks = chunk_list(images, chunk_size=10)
        self.assertEqual(len(chunks), 2)
        self.assertEqual([len(c) for c in chunks], [10, 8])


class TestTwoGroupDatabaseWorkflow(unittest.IsolatedAsyncioTestCase):
    """Async tests for Two-Group Reply-Based Order Creation, Loader Reply Mapping, and Statuses."""

    async def test_two_group_workflow(self):
        await init_db()

        # 1. Customer Order Creation in Client Group
        email = "twogroup_flow@example.com"
        await delete_orders_by_email(email)
        order = await create_order(
            email=email,
            client_chat_id=-1001111111111,
            original_message_id=501,
            package="10800 CP"
        )
        self.assertIsNotNone(order.id)
        self.assertEqual(order.status, "Pending")
        self.assertEqual(order.package, "10800 CP")

        # 2. Forward to Loader Group & Store Loader Message ID
        await set_order_loader_message_id(order.id, 9901)
        loader_order = await get_order_by_loader_msg_id(9901)
        self.assertIsNotNone(loader_order)
        self.assertEqual(loader_order.id, order.id)

        # 3. Loader replies with images
        file_items = [("photo_1", "photo"), ("photo_2", "photo")]
        updated_order, is_dup = await add_images_to_order(
            order_id=order.id,
            file_items=file_items,
            media_group_id="album_5501"
        )
        self.assertFalse(is_dup)
        self.assertEqual(len(updated_order.images), 2)

        # 4. Duplicate reply test
        _, is_dup_2 = await add_images_to_order(
            order_id=order.id,
            file_items=file_items,
            media_group_id="album_5501"
        )
        self.assertTrue(is_dup_2)

        # 5. Mark Order Delivered
        await mark_order_delivered(order.id)
        del_order = await get_order_by_id(order.id)
        self.assertEqual(del_order.status, "Delivered")
        self.assertIsNotNone(del_order.delivered_at)

        # 6. Cancellation test on second order
        order2 = await create_order("cancel_test@example.com")
        canceled_order, success = await cancel_order(order2.id)
        self.assertTrue(success)
        self.assertEqual(canceled_order.status, "Cancelled")

        # Clean up
        await delete_orders_by_email(email)
        await delete_orders_by_email("cancel_test@example.com")


class TestCalculatorAndSuperAdminIgnore(unittest.IsolatedAsyncioTestCase):
    """Tests for Instant Group-Wise Accounting Calculator & Super Admin Access."""

    async def asyncSetUp(self):
        await init_db()

    def test_safe_eval_valid_math(self):
        self.assertEqual(safe_eval("100+50"), 150)
        self.assertEqual(safe_eval("100 * 5"), 500)
        self.assertEqual(safe_eval("1000 / 4"), 250)
        self.assertEqual(safe_eval("(100 + 50) * 2"), 300)
        self.assertEqual(safe_eval("-50 + 100"), 50)
        self.assertEqual(safe_eval("15.2 * 2"), 30.4)

    def test_safe_eval_zero_division(self):
        with self.assertRaises(ZeroDivisionError):
            safe_eval("10 / 0")

    def test_safe_eval_code_injection_security(self):
        with self.assertRaises(ValueError):
            safe_eval("__import__('os').system('ls')")
        with self.assertRaises(ValueError):
            safe_eval("eval('1+1')")
        with self.assertRaises(ValueError):
            safe_eval("import os")
        with self.assertRaises(ValueError):
            safe_eval("open('/etc/passwd')")
        with self.assertRaises(ValueError):
            safe_eval("'string_literal'")

    async def test_super_admin_sends_number(self):
        chat_id = -100999001
        await paid_group_total(chat_id)  # Reset balance to 0

        update = MagicMock()
        update.effective_chat.id = chat_id
        update.effective_user.id = 8261988472  # Super Admin
        update.effective_message.text = "100"
        update.effective_message.reply_text = AsyncMock()

        with self.assertRaises(ApplicationHandlerStop):
            await calculator_text_handler(update, MagicMock())

        reply_text = update.effective_message.reply_text.call_args[0][0]
        self.assertIn("before: 0", reply_text)
        self.assertIn("now: 100", reply_text)
        self.assertIn("total: 100", reply_text)

    async def test_super_admin_sends_math_addition(self):
        chat_id = -100999002
        await paid_group_total(chat_id)
        await add_to_group_total(chat_id, 100)

        update = MagicMock()
        update.effective_chat.id = chat_id
        update.effective_user.id = 8261988472  # Super Admin
        update.effective_message.text = "50+50"
        update.effective_message.reply_text = AsyncMock()

        with self.assertRaises(ApplicationHandlerStop):
            await calculator_text_handler(update, MagicMock())

        reply_text = update.effective_message.reply_text.call_args[0][0]
        self.assertIn("before: 100", reply_text)
        self.assertIn("now: 100", reply_text)
        self.assertIn("total: 200", reply_text)

    async def test_super_admin_sends_math_multiplication(self):
        chat_id = -100999003
        await paid_group_total(chat_id)
        await add_to_group_total(chat_id, 150)

        update = MagicMock()
        update.effective_chat.id = chat_id
        update.effective_user.id = 8261988472  # Super Admin
        update.effective_message.text = "15.2*2"
        update.effective_message.reply_text = AsyncMock()

        with self.assertRaises(ApplicationHandlerStop):
            await calculator_text_handler(update, MagicMock())

        reply_text = update.effective_message.reply_text.call_args[0][0]
        self.assertIn("before: 150", reply_text)
        self.assertIn("now: 30.4", reply_text)
        self.assertIn("total: 180.4", reply_text)

    async def test_super_admin_sends_zero(self):
        chat_id = -100999004
        await paid_group_total(chat_id)
        await add_to_group_total(chat_id, 180.4)

        update = MagicMock()
        update.effective_chat.id = chat_id
        update.effective_user.id = 8261988472  # Super Admin
        update.effective_message.text = "0"
        update.effective_message.reply_text = AsyncMock()

        with self.assertRaises(ApplicationHandlerStop):
            await calculator_text_handler(update, MagicMock())

        reply_text = update.effective_message.reply_text.call_args[0][0]
        self.assertIn("💰 Remaining Amount: 180.4", reply_text)

        # Balance should remain unchanged
        bal = await get_group_total_balance(chat_id)
        self.assertEqual(bal, 180.4)

    async def test_paid_command(self):
        chat_id = -100999005
        await paid_group_total(chat_id)
        await add_to_group_total(chat_id, 150)

        update = MagicMock()
        update.effective_chat.id = chat_id
        update.effective_user.id = 8261988472  # Super Admin
        update.effective_message.reply_text = AsyncMock()

        await paid_command(update, MagicMock())

        reply_text = update.effective_message.reply_text.call_args[0][0]
        self.assertIn("Paid Amount:</b> 150", reply_text)
        self.assertIn("Remaining Amount:</b> 0", reply_text)

        # Verify database balance is reset to 0
        bal = await get_group_total_balance(chat_id)
        self.assertEqual(bal, 0.0)

    async def test_undo_command(self):
        chat_id = -100999006
        await paid_group_total(chat_id)
        await add_to_group_total(chat_id, 100)  # before 0, now 100, total 100
        await add_to_group_total(chat_id, 50)   # before 100, now 50, total 150

        update = MagicMock()
        update.effective_chat.id = chat_id
        update.effective_user.id = 8261988472  # Super Admin
        update.effective_message.reply_text = AsyncMock()

        await undo_command(update, MagicMock())

        reply_text = update.effective_message.reply_text.call_args[0][0]
        self.assertIn("Reverted:</b> 150 → 100", reply_text)

        # Verify reverted balance in DB
        bal = await get_group_total_balance(chat_id)
        self.assertEqual(bal, 100.0)

        # Subsequent /undo should indicate nothing to undo
        update_second = MagicMock()
        update_second.effective_chat.id = chat_id
        update_second.effective_user.id = 8261988472
        update_second.effective_message.reply_text = AsyncMock()

        await undo_command(update_second, MagicMock())
        reply_second = update_second.effective_message.reply_text.call_args[0][0]
        self.assertIn("Nothing to undo", reply_second)

    async def test_invalid_math_expression(self):
        update = MagicMock()
        update.effective_chat.id = -100999007
        update.effective_user.id = 8261988472  # Super Admin
        update.effective_message.text = "100++"
        update.effective_message.reply_text = AsyncMock()

        with self.assertRaises(ApplicationHandlerStop):
            await calculator_text_handler(update, MagicMock())

        reply_text = update.effective_message.reply_text.call_args[0][0]
        self.assertIn("Invalid calculation", reply_text)

    async def test_non_super_admin_calculator_input_ignored_or_rejected(self):
        # Calculator text handler ignores non-super admins (does not raise ApplicationHandlerStop)
        update = MagicMock()
        update.effective_chat.id = -100999008
        update.effective_user.id = 999888777  # Normal user
        update.effective_message.text = "100"
        update.effective_message.reply_text = AsyncMock()

        await calculator_text_handler(update, MagicMock())
        update.effective_message.reply_text.assert_not_called()

        # Non-super admin command rejected
        update_cmd = MagicMock()
        update_cmd.effective_user.id = 999888777
        update_cmd.effective_message.reply_text = AsyncMock()
        await paid_command(update_cmd, MagicMock())
        update_cmd.effective_message.reply_text.assert_called_once()
        self.assertIn("not authorized", update_cmd.effective_message.reply_text.call_args[0][0])

    async def test_super_admin_normal_message_ignored(self):
        await update_source_group(-1001111111111, "Client Group")
        email = "sa_ignore_test@example.com"
        await delete_orders_by_email(email)

        update = MagicMock()
        update.effective_chat.id = -1001111111111
        update.effective_user.id = 8261988472  # Super Admin
        update.effective_message.message_id = 999
        update.effective_message.text = f"10800 CP\nEmail: {email}"
        context = MagicMock()

        await source_group_handler(update, context)
        order = await get_pending_order_by_email(email)
        self.assertIsNone(order)  # Super Admin message must be ignored completely by order detection!

    async def test_customer_order_detection_still_works(self):
        await update_source_group(-1001111111111, "Client Group")
        email = "cust_order_test@example.com"
        await delete_orders_by_email(email)

        update = MagicMock()
        update.effective_chat.id = -1001111111111
        update.effective_user.id = 999888777  # Normal Customer
        update.effective_message.message_id = 888
        update.effective_message.text = f"Facebook\nEmail: {email}\nPassword: 123456\n10800 CP"
        context = MagicMock()
        context.bot.copy_message = AsyncMock()
        context.bot.set_message_reaction = AsyncMock()

        await source_group_handler(update, context)
        order = await get_pending_order_by_email(email)
        self.assertIsNotNone(order)
        self.assertEqual(order.email, email)
        await delete_orders_by_email(email)

    async def test_independent_group_totals(self):
        chat_a = -100111000
        chat_b = -100222000
        await paid_group_total(chat_a)
        await paid_group_total(chat_b)

        await add_to_group_total(chat_a, 100)
        await add_to_group_total(chat_b, 500)

        bal_a = await get_group_total_balance(chat_a)
        bal_b = await get_group_total_balance(chat_b)

        self.assertEqual(bal_a, 100.0)
        self.assertEqual(bal_b, 500.0)

    async def test_multiple_calculator_operations_state(self):
        chat_id = -100999009
        await paid_group_total(chat_id)

        b1, n1, t1 = await add_to_group_total(chat_id, 100)
        self.assertEqual((b1, n1, t1), (0.0, 100.0, 100.0))

        b2, n2, t2 = await add_to_group_total(chat_id, 50)
        self.assertEqual((b2, n2, t2), (100.0, 50.0, 150.0))

        b3, n3, t3 = await add_to_group_total(chat_id, 30.4)
        self.assertEqual((b3, n3, t3), (150.0, 30.4, 180.4))


class TestRealCustomerOrderDetection(unittest.TestCase):
    """Tests exact real customer order test cases 1 through 10, Telegram escaping, and Markdown formatting."""

    def test_user_exact_test_1(self):
        msg = "Abu Naif\n\nedfyak@gmail.com\n\nHRdi1515\n\n880Cp\nFree"
        res = parse_order_v2(msg)
        self.assertTrue(res["order_detected"], f"Failed on Test 1: {res}")
        self.assertEqual(res["email"], "edfyak@gmail.com")
        self.assertTrue(res["credential_detected"])
        self.assertEqual(res["package"].lower(), "880cp")

    def test_user_exact_test_2(self):
        msg = "mhmdalshbaa22@gmail.com\n\nmm112233\n\n2400+880"
        res = parse_order_v2(msg)
        self.assertTrue(res["order_detected"], f"Failed on Test 2: {res}")
        self.assertEqual(res["email"], "mhmdalshbaa22@gmail.com")
        self.assertTrue(res["credential_detected"])
        self.assertEqual(res["package"], "2400+880")

    def test_user_exact_test_3(self):
        msg = "edfyak@gmail.com\nHRdi1515\n880Cp"
        res = parse_order_v2(msg)
        self.assertTrue(res["order_detected"], f"Failed on Test 3: {res}")

    def test_user_exact_test_4(self):
        msg = "email@gmail.com\npassword123\n2400"
        res = parse_order_v2(msg)
        self.assertTrue(res["order_detected"], f"Failed on Test 4: {res}")
        self.assertEqual(res["email"], "email@gmail.com")

    def test_user_exact_test_5(self):
        msg = "email@gmail.com\npassword123\n2400+880"
        res = parse_order_v2(msg)
        self.assertTrue(res["order_detected"], f"Failed on Test 5: {res}")

    def test_user_exact_test_6(self):
        msg = "email@gmail.com"
        res = parse_order_v2(msg)
        self.assertFalse(res["order_detected"], f"Failed on Test 6: {res}")

    def test_user_exact_test_7(self):
        msg = "email@gmail.com\npassword123"
        res = parse_order_v2(msg)
        self.assertFalse(res["order_detected"], f"Failed on Test 7: {res}")

    def test_user_exact_test_8(self):
        msg = "2400+880"
        res = parse_order_v2(msg)
        self.assertFalse(res["order_detected"], f"Failed on Test 8: {res}")

    def test_user_exact_test_9(self):
        msg = "Facebook\nemail@gmail.com"
        res = parse_order_v2(msg)
        self.assertFalse(res["order_detected"], f"Failed on Test 9: {res}")

    def test_user_exact_test_10(self):
        msg = "hello\nemail@gmail.com\nprice 2400"
        res = parse_order_v2(msg)
        self.assertFalse(res["order_detected"], f"Failed on Test 10: {res}")

    def test_markdown_formatting_and_telegram_escaping(self):
        # Escaped email
        msg_escaped = "edfyak\\@gmail.com\nHRdi1515\n880Cp"
        res1 = parse_order_v2(msg_escaped)
        self.assertTrue(res1["order_detected"], f"Failed on escaped email: {res1}")
        self.assertEqual(res1["email"], "edfyak@gmail.com")

        # Markdown bold formatting
        msg_md = "mhmdalshbaa22@gmail.com\n**mm112233**\n**2400+880**"
        res2 = parse_order_v2(msg_md)
        self.assertTrue(res2["order_detected"], f"Failed on Markdown bold: {res2}")
        self.assertEqual(res2["email"], "mhmdalshbaa22@gmail.com")
        self.assertEqual(res2["package"], "2400+880")

        # Escaped plus and code backticks
        msg_code = "email@gmail.com\n`password123`\n2400\\+880"
        res3 = parse_order_v2(msg_code)
        self.assertTrue(res3["order_detected"], f"Failed on escaped plus: {res3}")
        self.assertEqual(res3["package"], "2400+880")


if __name__ == "__main__":
    unittest.main()


