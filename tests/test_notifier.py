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
from unittest.mock import Mock, patch

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

    def _add_notification(self, channel_id, backend):
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

    def _notification_row(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM notifications").fetchone()
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
        # 新增測試資料
        self._add_notification("telegram_main", "apprise")

        # 模擬 Apprise
        with patch.dict(os.environ, {"TELEGRAM_APPRISE_URL": "tgram://token/chat"}):
            with patch("src.notifier.apprise.Apprise") as mock_apprise:
                mock_apobj = Mock()
                mock_apprise.return_value = mock_apobj
                mock_apobj.notify = Mock(return_value=True)

                from src.notifier import Notifier

                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()

                mock_apobj.notify.assert_called_once()
        self.assertEqual(self._notification_row()["status"], "sent")

    def test_send_pending_line(self):
        """測試 LINE 通知發送"""
        # 新增測試資料
        self._add_notification("line_main", "line")

        # 模擬 LINE API
        mock_response = Mock()
        mock_response.json.return_value = {
            "statuses": [
                {"status": "200", "requestId": "req_123", "is_duplicate": False}
            ]
        }
        mock_response.status_code = 200
        mock_response.headers = {"x-line-request-id": "req_123"}

        with patch("requests.post", return_value=mock_response):
            with patch.dict(
                os.environ,
                {
                    "LINE_CHANNEL_ACCESS_TOKEN": "test_token",
                    "LINE_TO": "test_user_id",
                },
            ):
                from src.notifier import Notifier

                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()

                # 檢查 LINE 發送成功
                self.logger.info.assert_called()
        self.assertEqual(self._notification_row()["status"], "sent")

    def test_line_idempotent_retry_uuid(self):
        """測試 LINE idempotent retry 使用 UUID"""
        self._add_notification("line_main", "line")
        # 模擬 LINE API
        mock_response = Mock()
        mock_response.json.return_value = {
            "statuses": [
                {"status": "200", "requestId": "req_123", "is_duplicate": False}
            ]
        }
        mock_response.status_code = 200
        mock_response.headers = {}

        captured_headers = {}

        def capture_headers(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return mock_response

        with patch("requests.post", side_effect=capture_headers):
            with patch.dict(
                os.environ,
                {
                    "LINE_CHANNEL_ACCESS_TOKEN": "test_token",
                    "LINE_TO": "test_user_id",
                },
            ):
                from src.notifier import Notifier

                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()

                # 檢查 X-Line-Retry-Key header 存在且為 UUID 格式
                self.assertIn("X-Line-Retry-Key", captured_headers)
                retry_key = captured_headers["X-Line-Retry-Key"]
                # 驗證 UUID 格式
                uuid.UUID(retry_key)  # 不拋出異常表示是有效 UUID

    def test_line_409_conflict_as_success(self):
        """測試 LINE 409 衝突視為成功"""
        self._add_notification("line_main", "line")
        # 模擬 LINE API 返回 409
        mock_response = Mock()
        mock_response.status_code = 409
        mock_response.text = "Conflict"
        mock_response.headers = {"x-line-accepted-request-id": "accepted_123"}

        with patch("requests.post", return_value=mock_response):
            with patch.dict(
                os.environ,
                {
                    "LINE_CHANNEL_ACCESS_TOKEN": "test_token",
                    "LINE_TO": "test_user_id",
                },
            ):
                from src.notifier import Notifier

                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()

                # 檢查視為成功
                self.logger.info.assert_called()
        self.assertEqual(self._notification_row()["status"], "sent")

    def test_line_5xx_save_retry_key(self):
        """測試 LINE 5xx 錯誤保存 retry_key 以便重試"""
        self._add_notification("line_main", "line")
        # 模擬 LINE API 返回 500
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"
        mock_response.headers = {}

        with patch("requests.post", return_value=mock_response):
            with patch.dict(
                os.environ,
                {
                    "LINE_CHANNEL_ACCESS_TOKEN": "test_token",
                    "LINE_TO": "test_user_id",
                },
            ):
                from src.notifier import Notifier

                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()

                # 檢查警告被記錄
                self.logger.warning.assert_called()
        row = self._notification_row()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["attempts"], 1)
        self.assertIsNotNone(row["next_retry_at"])
        uuid.UUID(row["retry_key"])

    def test_line_timeout_save_retry_key(self):
        """測試 LINE timeout 保存 retry_key 以便重試"""
        import requests

        self._add_notification("line_main", "line")

        with patch(
            "requests.post", side_effect=requests.exceptions.Timeout("Request timeout")
        ):
            with patch.dict(
                os.environ,
                {
                    "LINE_CHANNEL_ACCESS_TOKEN": "test_token",
                    "LINE_TO": "test_user_id",
                },
            ):
                from src.notifier import Notifier

                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()

                # 檢查警告被記錄
                self.logger.warning.assert_called()
        row = self._notification_row()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["attempts"], 1)
        uuid.UUID(row["retry_key"])

    def test_line_retry_reuses_the_same_key(self):
        """退避後重試必須沿用第一次請求的 retry key。"""
        import requests

        self._add_notification("line_main", "line")
        successful_response = Mock(
            status_code=200,
            headers={"x-line-request-id": "request_123"},
        )
        captured_keys = []

        def send(*args, **kwargs):
            captured_keys.append(kwargs["headers"]["X-Line-Retry-Key"])
            if len(captured_keys) == 1:
                raise requests.exceptions.Timeout("Request timeout")
            return successful_response

        environment = {
            "LINE_CHANNEL_ACCESS_TOKEN": "test_token",
            "LINE_TO": "test_user_id",
        }
        with patch("requests.post", side_effect=send), patch.dict(
            os.environ, environment
        ):
            from src.notifier import Notifier

            notifier = Notifier(self.config, self.logger)
            notifier.send_pending()

            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "UPDATE notifications SET next_retry_at = ? WHERE id = 1",
                ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
            )
            conn.commit()
            conn.close()

            notifier.send_pending()

        self.assertEqual(len(captured_keys), 2)
        self.assertEqual(captured_keys[0], captured_keys[1])
        self.assertEqual(self._notification_row()["status"], "sent")

    def test_line_4xx_is_not_retried(self):
        """請求錯誤不會透過重試改變結果。"""
        self._add_notification("line_main", "line")
        response = Mock(status_code=400, text="Bad Request", headers={})

        with patch("requests.post", return_value=response), patch.dict(
            os.environ,
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "test_token",
                "LINE_TO": "test_user_id",
            },
        ):
            from src.notifier import Notifier

            Notifier(self.config, self.logger).send_pending()

        row = self._notification_row()
        self.assertEqual(row["status"], "failed")
        self.assertIsNone(row["next_retry_at"])

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
        update_notification_status(self.db_path, telegram_id, "retry", "Telegram error")

        # line 成功
        update_notification_status(self.db_path, line_id, "sent")

        # 退避到期後，只有 Telegram 回到待重試清單。
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
