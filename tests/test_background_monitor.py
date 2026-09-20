"""Headless-only polling, session pause, cleanup, state and lifecycle tests."""

import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from src.background_monitor import (
    BackgroundReader,
    RuntimeState,
    LoginRequired,
    ReadUnavailable,
    import_cookies,
    instance_lock,
    manual_login,
    parse_cookie_data,
)
from src.database import init_database, get_pending_notifications
from src.observation_store import BrowserStore
from main import run_monitor


class TestBackgroundMonitor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = str(self.root / "test.db")
        init_database(self.path)
        self.target = {
            "page_id": "123",
            "url": "https://www.facebook.com/example",
            "enabled": True,
        }
        self.store = BrowserStore(
            {"storage": {"database": self.path}, "targets": [self.target]}
        )
        self.state = RuntimeState(self.path)
        self.state.set("login_required", False)
        self.page = Mock(url=self.target["url"])
        self.page.locator.return_value.first.is_visible.return_value = False
        self.page.goto.return_value.status = 200
        self.page.evaluate.return_value = [
            {"url": "https://www.facebook.com/example/posts/one", "summary": "hello"}
        ]
        self.context = Mock(pages=[self.page])
        self.playwright = Mock()
        self.playwright.chromium.launch_persistent_context.return_value = self.context
        self.factory = Mock(side_effect=lambda: nullcontext(self.playwright))
        self.reader = BackgroundReader(
            self.root / "profile", self.store, self.state, self.factory
        )

    def test_headless_single_context_closes_after_cycle_and_baseline_is_silent(self):
        self.reader.poll()
        options = self.playwright.chromium.launch_persistent_context.call_args.kwargs
        self.assertIs(options["headless"], True)
        self.assertIs(options["accept_downloads"], False)
        self.context.close.assert_called_once()
        self.assertEqual(self.state.get("target:123")["status"], "observed")
        self.assertEqual(get_pending_notifications(self.path), [])
        self.assertEqual(self.store.status()[0]["observed_count"], 1)
        self.assertIn("rss_mb_sample", self.state.get("resources"))

    def test_login_challenge_pauses_persistently_without_opening_visible_browser(self):
        self.page.url = "https://www.facebook.com/checkpoint/"
        self.reader.poll()
        self.assertTrue(self.state.get("login_required"))
        self.assertEqual(self.state.get("phase"), "login_required")
        self.reader.poll()
        self.factory.assert_called_once()
        self.context.close.assert_called_once()
        self.assertEqual(self.store.status()[0]["observed_count"], 0)

    def test_unconfigured_session_never_launches(self):
        self.state.set("login_required", True)
        self.reader.poll()
        self.factory.assert_not_called()

    def test_success_timestamp_survives_later_parse_failure(self):
        self.reader.poll()
        success = self.state.get("target:123")["last_success_at"]
        self.page.evaluate.return_value = []
        self.reader.poll()
        self.assertEqual(self.state.get("target:123")["last_success_at"], success)
        self.assertEqual(self.state.get("target:123")["status"], "unavailable")

    def test_manual_login_is_only_visible_path_and_keeps_failed_login_paused(self):
        self.page.url = "https://www.facebook.com/login/"
        with patch("builtins.input", return_value=""), self.assertRaises(LoginRequired):
            manual_login(self.root / "profile", self.state, self.factory)
        options = self.playwright.chromium.launch_persistent_context.call_args.kwargs
        self.assertIs(options["headless"], False)
        self.assertTrue(self.state.get("login_required"))
        self.context.close.assert_called_once()

    def test_quiet_browser_dialogs_are_dismissed(self):
        self.reader.poll()
        callback = next(
            call.args[1]
            for call in self.page.on.call_args_list
            if call.args[0] == "dialog"
        )
        dialog = Mock()
        callback(dialog)
        dialog.dismiss.assert_called_once()

    def test_empty_parse_is_failure_not_empty_success(self):
        self.page.evaluate.return_value = []
        self.reader.poll()
        self.assertEqual(
            self.state.get("target:123")["reason"], "no_recognizable_posts"
        )
        self.assertEqual(self.store.status()[0]["observed_count"], 0)
        self.context.close.assert_called_once()

    def test_http_rate_limit_does_not_store_posts(self):
        self.page.goto.return_value.status = 429
        self.reader.poll()
        self.assertEqual(self.state.get("target:123")["status"], "unavailable")
        self.assertFalse(self.state.get("login_required"))

    def test_redirect_does_not_relabel_other_page(self):
        self.page.url = "https://www.facebook.com/other"
        with self.assertRaises(ReadUnavailable):
            self.reader.read_target(self.page, self.target)

    def test_access_denied_requires_user_intervention(self):
        self.page.goto.return_value.status = 403
        with self.assertRaises(LoginRequired):
            self.reader.read_target(self.page, self.target)

    def test_instance_lock_blocks_second_reader_and_releases(self):
        with instance_lock(self.root):
            with self.assertRaises(RuntimeError):
                with instance_lock(self.root):
                    self.fail("Second lock acquired")
        with instance_lock(self.root):
            pass

    def test_run_once_sends_pending_and_marks_stopped(self):
        reader, notifier = Mock(), Mock()
        run_monitor(reader, self.state, notifier, 300, once=True)
        reader.poll.assert_called_once()
        notifier.send_pending.assert_called_once()
        self.assertEqual(self.state.get("phase"), "stopped")
        self.assertIsNone(self.state.get("pid"))

    def test_stop_is_checked_without_waiting_for_next_poll(self):
        reader, notifier = Mock(), Mock()
        with patch(
            "main.time.sleep",
            side_effect=lambda _: self.state.set("stop_requested", True),
        ):
            run_monitor(reader, self.state, notifier, 300)
        reader.poll.assert_called_once()
        self.assertEqual(self.state.get("phase"), "stopped")

    def test_parse_cookie_data_header_string_and_json(self):
        header = "c_user=10001; xs=sec_tok; datr=dev_id"
        parsed = parse_cookie_data(header)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0], {"name": "c_user", "value": "10001", "domain": ".facebook.com", "path": "/"})

        json_arr = '[{"name": "c_user", "value": "20002", "domain": ".facebook.com"}]'
        parsed_json = parse_cookie_data(json_arr)
        self.assertEqual(parsed_json[0]["name"], "c_user")
        self.assertEqual(parsed_json[0]["value"], "20002")

    def test_import_cookies_success_and_saves_state(self):
        self.page.url = "https://www.facebook.com/"
        import_cookies(self.root / "profile", self.state, "c_user=10001; xs=sec_tok", self.factory)
        self.assertFalse(self.state.get("login_required"))
        self.assertEqual(self.state.get("phase"), "login_saved_unverified")
        self.context.add_cookies.assert_called_once()

    def test_import_cookies_failed_when_still_login_required(self):
        self.page.url = "https://www.facebook.com/login/"
        with self.assertRaises(LoginRequired):
            import_cookies(self.root / "profile", self.state, "c_user=expired", self.factory)
        self.assertTrue(self.state.get("login_required"))

