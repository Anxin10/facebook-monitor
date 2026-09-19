"""通知模組測試

涵蓋：
- Apprise 呼叫
- LINE 重試回應
- 逐目的地重試
- 通知狀態管理
- LINE idempotent retry
"""

import unittest
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
import json

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# 需要先在記憶體中建立資料庫
from database import init_database, add_item, add_notifications


class TestNotifier(unittest.TestCase):
    """通知模組測試"""

    def setUp(self):
        """測試準備"""
        # 建立臨時資料庫
        import tempfile

        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        init_database(self.db_path)

        self.config = {
            "storage": {"database": self.db_path},
            "notifications": {
                "timezone": "Asia/Taipei",
                "channels": [
                    {
                        "id": "telegram_main",
                        "backend": "apprise",
                        "url_env": "TELEGRAM_APPRISE_URL",
                    },
                    {
                        "id": "line_main",
                        "backend": "line",
                        "token_env": "LINE_CHANNEL_ACCESS_TOKEN",
                        "recipient_env": "LINE_TO",
                    },
                ],
            },
        }

        self.logger = Mock()

    def tearDown(self):
        """清理"""
        import shutil

        shutil.rmtree(self.temp_dir)

    def _seed_notification(self, channel_id: str, backend: str) -> None:
        add_item(
            self.db_path,
            "test_page",
            "post",
            "post_1",
            author_id="author_1",
            published_at=datetime.now(timezone.utc),
            summary="Test post",
            url="https://facebook.com/posts/post_1",
        )
        add_notifications(
            self.db_path,
            "test_page",
            "post",
            "post_1",
            [{"id": channel_id, "backend": backend}],
        )

    def _notification_row(self, channel_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM notifications WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        conn.close()
        return row

    def test_send_pending_no_channels(self):
        """測試無管道設定"""
        config = self.config.copy()
        config["notifications"] = {"timezone": "Asia/Taipei", "channels": []}

        from notifier import Notifier

        notifier = Notifier(config, self.logger)
        notifier.send_pending()

        self.logger.debug.assert_called()

    def test_send_pending_apprise(self):
        """測試 Apprise 通知發送"""
        self._seed_notification("telegram_main", "apprise")

        # 模擬 Apprise
        with patch.dict(os.environ, {"TELEGRAM_APPRISE_URL": "tgram://test/test"}):
            with patch("apprise.Apprise") as mock_apprise:
                mock_apobj = Mock()
                mock_apprise.return_value = mock_apobj
                mock_apobj.notify = Mock(return_value=True)

                from notifier import Notifier

                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()

                mock_apobj.notify.assert_called_once()
                self.assertEqual(
                    self._notification_row("telegram_main")["status"], "sent"
                )

    def test_send_pending_line(self):
        """測試 LINE 通知發送"""
        self._seed_notification("line_main", "line")

        # 模擬 LINE API
        mock_response = Mock()
        mock_response.status_code = 200

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_ACCESS_TOKEN": "test_token", "LINE_TO": "test_user_id"},
        ):
            with patch("requests.post", return_value=mock_response):
                from notifier import Notifier

                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()
                self.logger.info.assert_called()
                self.assertEqual(self._notification_row("line_main")["status"], "sent")

    def test_line_idempotent_retry_uuid(self):
        """測試 LINE idempotent retry 使用 UUID"""
        self._seed_notification("line_main", "line")
        # 模擬 LINE API
        mock_response = Mock()
        mock_response.status_code = 200

        captured_headers = {}

        def capture_headers(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return mock_response

        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_ACCESS_TOKEN": "test_token", "LINE_TO": "test_user_id"},
        ):
            with patch("requests.post", side_effect=capture_headers):
                from notifier import Notifier

                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()
                self.assertIn("X-Line-Retry-Key", captured_headers)
                retry_key = captured_headers["X-Line-Retry-Key"]
                uuid.UUID(retry_key)
                row = self._notification_row("line_main")
                self.assertEqual(row["status"], "sent")
                self.assertEqual(row["retry_key"], retry_key)

    def test_line_409_conflict_as_success(self):
        """測試 LINE 409 衝突視為成功"""
        self._seed_notification("line_main", "line")
        # 模擬 LINE API 返回 409
        mock_response = Mock()
        mock_response.status_code = 409
        mock_response.text = "Conflict"
        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_ACCESS_TOKEN": "test_token", "LINE_TO": "test_user_id"},
        ):
            with patch("requests.post", return_value=mock_response):
                from notifier import Notifier

                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()
                self.logger.info.assert_called()
                row = self._notification_row("line_main")
                self.assertEqual(row["status"], "sent")
                uuid.UUID(row["retry_key"])

    def test_line_5xx_save_retry_key(self):
        """測試 LINE 5xx 錯誤保存 retry_key 以便重試"""
        self._seed_notification("line_main", "line")
        # 模擬 LINE API 返回 500
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"
        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_ACCESS_TOKEN": "test_token", "LINE_TO": "test_user_id"},
        ):
            with patch("requests.post", return_value=mock_response):
                from notifier import Notifier

                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()
                self.logger.warning.assert_called()
                row = self._notification_row("line_main")
                self.assertEqual(row["status"], "pending")
                self.assertEqual(row["attempts"], 1)
                self.assertIsNotNone(row["next_retry_at"])
                uuid.UUID(row["retry_key"])

    def test_line_timeout_save_retry_key(self):
        """測試 LINE timeout 保存 retry_key 以便重試"""
        import requests

        self._seed_notification("line_main", "line")
        with patch.dict(
            os.environ,
            {"LINE_CHANNEL_ACCESS_TOKEN": "test_token", "LINE_TO": "test_user_id"},
        ):
            with patch(
                "requests.post",
                side_effect=requests.exceptions.Timeout("Request timeout"),
            ):
                from notifier import Notifier

                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()
                self.logger.warning.assert_called()
                row = self._notification_row("line_main")
                self.assertEqual(row["status"], "pending")
                self.assertEqual(row["attempts"], 1)
                self.assertIsNotNone(row["next_retry_at"])
                uuid.UUID(row["retry_key"])

    def test_per_channel_retry(self):
        """測試逐目的地重試"""
        # 新增兩個 channel 的通知
        add_item(self.db_path, "test_page", "post", "post_1", author_id="author_1")

        channels = [
            {"id": "telegram_main", "backend": "apprise"},
            {"id": "line_main", "backend": "line"},
        ]

        add_notifications(self.db_path, "test_page", "post", "post_1", channels)

        from database import get_pending_notifications, update_notification_status

        # 取得通知
        pending = get_pending_notifications(self.db_path)
        self.assertEqual(len(pending), 2)

        # 模擬 telegram 失敗，line 成功
        telegram_id = [n["id"] for n in pending if n["channel_id"] == "telegram_main"][
            0
        ]
        line_id = [n["id"] for n in pending if n["channel_id"] == "line_main"][0]

        # telegram 失敗
        update_notification_status(
            self.db_path, telegram_id, "failed", "Telegram error"
        )

        # line 成功
        update_notification_status(self.db_path, line_id, "sent")

        # backoff 尚未到期，因此目前沒有可立即重試的通知
        self.assertEqual(get_pending_notifications(self.db_path), [])

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE notifications SET next_retry_at = ? WHERE id = ?",
            (
                (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                telegram_id,
            ),
        )
        conn.commit()
        conn.close()

        pending = get_pending_notifications(self.db_path)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["channel_id"], "telegram_main")

    def test_notification_message_format(self):
        """測試通知訊息格式"""
        from notifier import Notifier

        notifier = Notifier(self.config, self.logger)

        notification = {
            "page_id": "test_page",
            "content_type": "post",
            "content_id": "post_1",
            "channel_id": "telegram_main",
            "summary": "This is a test post message",
            "url": "https://facebook.com/posts/post_1",
            "published_at": "2026-09-18T10:00:00+00:00",
        }

        message = notifier._build_message(notification)

        self.assertIn("Facebook 新內容通知", message)
        self.assertIn("test_page", message)
        self.assertIn("post_1", message)
        self.assertIn("https://facebook.com/posts/post_1", message)

    def test_timezone_handling(self):
        """測試時區處理"""
        from notifier import Notifier

        notifier = Notifier(self.config, self.logger)

        notification = {
            "page_id": "test_page",
            "content_type": "post",
            "content_id": "post_1",
            "channel_id": "telegram_main",
            "summary": "Test",
            "url": "https://facebook.com/posts/post_1",
            "published_at": "2026-09-18T10:00:00+00:00",
        }

        message = notifier._build_message(notification)

        # 應該包含格式化後的時間
        self.assertIn("發布時間", message)


if __name__ == "__main__":
    unittest.main()
