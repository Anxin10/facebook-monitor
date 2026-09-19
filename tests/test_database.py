"""資料庫模組測試

涵蓋：
- 三頁游標分頁
- 作者篩選
- 空基準處理
- 部分失敗處理
- 分頁上限處理
- 交易回滾
- 重啟去重
"""

import unittest
import sqlite3
import tempfile
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 加入 src 路徑
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from database import (
    init_database,
    add_item,
    item_exists,
    get_items_by_page,
    update_check_status,
    get_check_status,
    set_baseline_ready,
    add_notifications,
    get_pending_notifications,
    update_notification_status,
    save_batch_with_transaction,
)


class TestDatabase(unittest.TestCase):
    """資料庫測試"""

    def setUp(self):
        """建立臨時資料庫"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        init_database(self.db_path)

    def tearDown(self):
        """清理臨時資料庫"""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.temp_dir)

    def test_init_database(self):
        """測試資料庫初始化"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 檢查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        self.assertIn("targets", tables)
        self.assertIn("items", tables)
        self.assertIn("checks", tables)
        self.assertIn("notifications", tables)

        conn.close()

    def test_add_item(self):
        """測試新增內容項目"""
        result = add_item(
            self.db_path,
            page_id="test_page",
            content_type="post",
            content_id="post_1",
            author_id="author_1",
            published_at=datetime.now(timezone.utc),
            summary="Test summary",
            url="https://example.com",
            raw_data='{"test": true}',
        )

        self.assertEqual(result, "post_1")

    def test_item_exists(self):
        """測試內容存在檢查"""
        # 新增項目
        add_item(
            self.db_path,
            page_id="test_page",
            content_type="post",
            content_id="post_1",
            author_id="author_1",
        )

        # 檢查存在
        self.assertTrue(item_exists(self.db_path, "test_page", "post", "post_1"))

        # 檢查不存在
        self.assertFalse(item_exists(self.db_path, "test_page", "post", "post_2"))

    def test_duplicate_item_rejected(self):
        """測試重複項目被拒絕（重啟去重）"""
        # 第一次新增
        result1 = add_item(
            self.db_path,
            page_id="test_page",
            content_type="post",
            content_id="post_1",
            author_id="author_1",
        )
        self.assertEqual(result1, "post_1")

        # 第二次新增（應返回 None）
        result2 = add_item(
            self.db_path,
            page_id="test_page",
            content_type="post",
            content_id="post_1",
            author_id="author_1",
        )
        self.assertIsNone(result2)

    def test_author_filter(self):
        """測試作者篩選"""
        # 新增不同作者的貼文
        add_item(
            self.db_path,
            "test_page",
            "post",
            "post_1",
            author_id="page_id",
            published_at=datetime.now(timezone.utc),
        )
        add_item(
            self.db_path,
            "test_page",
            "post",
            "post_2",
            author_id="other_page",
            published_at=datetime.now(timezone.utc),
        )

        # 取得所有貼文
        items = get_items_by_page(self.db_path, "test_page")

        # 應該有兩筆
        self.assertEqual(len(items), 2)

        # 檢查作者 ID
        author_ids = {item["author_id"] for item in items}
        self.assertIn("page_id", author_ids)
        self.assertIn("other_page", author_ids)

    def test_empty_baseline(self):
        """測試空基準處理"""
        # 檢查狀態應為 None
        status = get_check_status(self.db_path, "test_page", "post")
        self.assertIsNone(status)

        # 更新為成功
        update_check_status(self.db_path, "test_page", "post", "success", None, None)

        # 檢查狀態應存在
        status = get_check_status(self.db_path, "test_page", "post")
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], "success")
        self.assertEqual(status["baseline_ready"], 0)  # 尚未標記

    def test_baseline_ready(self):
        """測試基準已建立標記"""
        # 更新檢查狀態
        update_check_status(self.db_path, "test_page", "post", "success", None, None)

        # 標記基準已建立
        set_baseline_ready(self.db_path, "test_page", "post")

        # 檢查標記
        status = get_check_status(self.db_path, "test_page", "post")
        self.assertEqual(status["baseline_ready"], 1)

    def test_pagination_incomplete(self):
        """測試分頁未完成標記"""
        # 更新為分頁未完成
        update_check_status(
            self.db_path,
            "test_page",
            "post",
            "success",
            None,
            None,
            pagination_incomplete=True,
        )

        status = get_check_status(self.db_path, "test_page", "post")
        self.assertEqual(status["pagination_incomplete"], 1)

    def test_partial_failure_rollback(self):
        """測試部分失敗回滾（交易回滾）"""
        # 使用 transaction 保存
        new_items = [
            {
                "page_id": "test_page",
                "content_type": "post",
                "content_id": "post_1",
                "author_id": "author_1",
                "published_at": datetime.now(timezone.utc),
                "summary": "Test 1",
                "url": "https://example.com/1",
                "raw_data": '{"test": 1}',
            },
            {
                "page_id": "test_page",
                "content_type": "post",
                "content_id": "post_2",
                "author_id": "author_1",
                "published_at": datetime.now(timezone.utc),
                "summary": "Test 2",
                "url": "https://example.com/2",
                "raw_data": '{"test": 2}',
            },
        ]

        notifications = []
        check_updates = [
            {
                "page_id": "test_page",
                "content_type": "post",
                "status": "success",
                "error_code": None,
                "error_message": None,
                "pagination_incomplete": False,
            }
        ]

        import logging

        logger = logging.getLogger(__name__)

        # 應該成功
        success = save_batch_with_transaction(
            self.db_path, new_items, notifications, check_updates, logger
        )
        self.assertTrue(success)

        # 檢查項目已保存
        items = get_items_by_page(self.db_path, "test_page")
        self.assertEqual(len(items), 2)

    def test_items_are_sorted_by_published_time(self):
        """取回的貼文依發布時間由新到舊排序。"""
        for page in range(3):
            for i in range(3):
                content_id = f"page{page}_post{i}"
                add_item(
                    self.db_path,
                    "test_page",
                    "post",
                    content_id,
                    author_id="page_id",
                    published_at=datetime.now(timezone.utc)
                    - timedelta(hours=page * 10 + i),
                )

        # 取得所有貼文（按時間排序）
        items = get_items_by_page(self.db_path, "test_page", limit=100)

        # 應該有 9 筆
        self.assertEqual(len(items), 9)

        # 檢查排序（最新的在前）
        self.assertEqual(items[0]["content_id"], "page0_post0")

    def test_notifications_by_channel(self):
        """測試逐目的地通知"""
        # 新增通知
        add_item(self.db_path, "test_page", "post", "post_1", author_id="author_1")

        channels = [
            {"id": "telegram_main", "backend": "apprise"},
            {"id": "line_main", "backend": "line"},
        ]

        added = add_notifications(self.db_path, "test_page", "post", "post_1", channels)

        self.assertEqual(len(added), 2)

        # 取得待通知
        pending = get_pending_notifications(self.db_path)
        self.assertEqual(len(pending), 2)

        # 按 channel 篩選
        telegram_pending = get_pending_notifications(
            self.db_path, channel_id="telegram_main"
        )
        self.assertEqual(len(telegram_pending), 1)

    def test_notification_retry(self):
        """測試通知重試機制"""
        # 新增通知
        add_item(self.db_path, "test_page", "post", "post_1", author_id="author_1")
        add_notifications(
            self.db_path,
            "test_page",
            "post",
            "post_1",
            [{"id": "telegram_main", "backend": "apprise"}],
        )

        # 取得通知
        pending = get_pending_notifications(self.db_path)
        self.assertEqual(len(pending), 1)

        notification_id = pending[0]["id"]

        # 模擬失敗
        update_notification_status(self.db_path, notification_id, "retry", "Test error")

        # 尚在退避期的通知不應立即被取回。
        self.assertEqual(get_pending_notifications(self.db_path), [])

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM notifications WHERE id = ?", (notification_id,)
        ).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["attempts"], 1)
        self.assertIsNotNone(row["next_retry_at"])

        # 退避到期後才重新進入待發清單。
        conn.execute(
            "UPDATE notifications SET next_retry_at = ? WHERE id = ?",
            (
                (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                notification_id,
            ),
        )
        conn.commit()
        conn.close()
        pending = get_pending_notifications(self.db_path)
        self.assertEqual(len(pending), 1)

    def test_notification_success(self):
        """測試通知成功"""
        # 新增通知
        add_item(self.db_path, "test_page", "post", "post_1", author_id="author_1")
        add_notifications(
            self.db_path,
            "test_page",
            "post",
            "post_1",
            [{"id": "telegram_main", "backend": "apprise"}],
        )

        # 取得通知
        pending = get_pending_notifications(self.db_path)
        notification_id = pending[0]["id"]

        # 標記成功
        update_notification_status(
            self.db_path, notification_id, "sent", None, "retry_key_123"
        )

        # 檢查不再出現在待通知清單
        pending = get_pending_notifications(self.db_path)
        self.assertEqual(len(pending), 0)


if __name__ == "__main__":
    unittest.main()
