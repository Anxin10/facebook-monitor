"""SQLite 資料庫模組

依 HYBRID_INTEGRATION.md 實作資料儲存與交易管理。
"""

import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """取得資料庫連接"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_database(db_path: str) -> None:
    """初始化資料庫"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # targets 表：監控對象
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS targets (
            page_id TEXT PRIMARY KEY,
            url TEXT,
            account_type TEXT DEFAULT 'page_assumed',
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # items 表：內容及去重資料
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id TEXT NOT NULL,
            content_type TEXT NOT NULL,
            content_id TEXT NOT NULL,
            author_id TEXT,
            published_at TIMESTAMP,
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            summary TEXT,
            url TEXT,
            raw_data TEXT,
            UNIQUE(page_id, content_type, content_id)
        )
    """
    )

    # 建立索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_page_id ON items(page_id)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_items_first_seen_at ON items(first_seen_at)"
    )

    # checks 表：各來源檢查狀態
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id TEXT NOT NULL,
            content_type TEXT NOT NULL,
            baseline_ready INTEGER DEFAULT 0,
            last_attempt_at TIMESTAMP,
            last_success_at TIMESTAMP,
            status TEXT,
            error_code TEXT,
            error_message TEXT,
            pagination_incomplete INTEGER DEFAULT 0,
            UNIQUE(page_id, content_type)
        )
    """
    )

    # notifications 表：待通知與重試紀錄
    # 每個 channel id 獨立追蹤
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id TEXT NOT NULL,
            content_type TEXT NOT NULL,
            content_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            backend TEXT,
            status TEXT DEFAULT 'pending',
            attempts INTEGER DEFAULT 0,
            next_retry_at TIMESTAMP,
            sent_at TIMESTAMP,
            error_message TEXT,
            retry_key TEXT,
            UNIQUE(page_id, content_type, content_id, channel_id)
        )
    """
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_channel ON notifications(channel_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_next_retry ON notifications(next_retry_at)"
    )

    conn.commit()
    conn.close()
    logging.info(f"資料庫初始化完成：{db_path}")


def add_or_update_target(
    db_path: str,
    page_id: str,
    url: str,
    account_type: str = "page_assumed",
    enabled: bool = True,
) -> None:
    """新增或更新監控目標"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO targets 
        (page_id, url, account_type, enabled, updated_at)
        VALUES (?, ?, ?, ?, ?)
    """,
        (page_id, url, account_type, 1 if enabled else 0, datetime.now(timezone.utc)),
    )

    conn.commit()
    conn.close()


def get_enabled_targets(db_path: str) -> List[Dict[str, Any]]:
    """取得所有啟用的監控目標"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM targets WHERE enabled = 1")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def add_item(
    db_path: str,
    page_id: str,
    content_type: str,
    content_id: str,
    author_id: Optional[str] = None,
    published_at: Optional[datetime] = None,
    summary: Optional[str] = None,
    url: Optional[str] = None,
    raw_data: Optional[str] = None,
) -> Optional[str]:
    """新增內容項目，返回 content_id 若成功新增，否則 None"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO items 
            (page_id, content_type, content_id, author_id, published_at, summary, url, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                page_id,
                content_type,
                content_id,
                author_id,
                published_at.isoformat() if published_at else None,
                summary,
                url,
                raw_data,
            ),
        )
        conn.commit()
        return content_id
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def item_exists(db_path: str, page_id: str, content_type: str, content_id: str) -> bool:
    """檢查內容是否已存在"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 1 FROM items 
        WHERE page_id = ? AND content_type = ? AND content_id = ?
    """,
        (page_id, content_type, content_id),
    )
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def get_items_by_page(
    db_path: str, page_id: str, content_type: Optional[str] = None, limit: int = 100
) -> List[Dict[str, Any]]:
    """取得指定粉專的內容項目"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    if content_type:
        cursor.execute(
            """
            SELECT * FROM items 
            WHERE page_id = ? AND content_type = ?
            ORDER BY COALESCE(published_at, first_seen_at) DESC, id DESC LIMIT ?
        """,
            (page_id, content_type, limit),
        )
    else:
        cursor.execute(
            """
            SELECT * FROM items 
            WHERE page_id = ?
            ORDER BY COALESCE(published_at, first_seen_at) DESC, id DESC LIMIT ?
        """,
            (page_id, limit),
        )

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_check_status(
    db_path: str,
    page_id: str,
    content_type: str,
    status: str,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    pagination_incomplete: bool = False,
    baseline_ready: Optional[bool] = None,
) -> None:
    """更新檢查狀態"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    now = datetime.now(timezone.utc)

    if baseline_ready is None:
        cursor.execute(
            """
            INSERT INTO checks
            (page_id, content_type, last_attempt_at, last_success_at, status,
             error_code, error_message, pagination_incomplete)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(page_id, content_type)
            DO UPDATE SET
                last_attempt_at = excluded.last_attempt_at,
                last_success_at = CASE WHEN excluded.status = 'success'
                                       THEN excluded.last_success_at
                                       ELSE checks.last_success_at END,
                status = excluded.status,
                error_code = excluded.error_code,
                error_message = excluded.error_message,
                pagination_incomplete = excluded.pagination_incomplete
        """,
            (
                page_id,
                content_type,
                now,
                now if status == "success" else None,
                status,
                error_code,
                error_message,
                1 if pagination_incomplete else 0,
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO checks
            (page_id, content_type, baseline_ready, last_attempt_at, last_success_at,
             status, error_code, error_message, pagination_incomplete)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(page_id, content_type)
            DO UPDATE SET
                baseline_ready = excluded.baseline_ready,
                last_attempt_at = excluded.last_attempt_at,
                last_success_at = CASE WHEN excluded.status = 'success'
                                       THEN excluded.last_success_at
                                       ELSE checks.last_success_at END,
                status = excluded.status,
                error_code = excluded.error_code,
                error_message = excluded.error_message,
                pagination_incomplete = excluded.pagination_incomplete
        """,
            (
                page_id,
                content_type,
                1 if baseline_ready else 0,
                now,
                now if status == "success" else None,
                status,
                error_code,
                error_message,
                1 if pagination_incomplete else 0,
            ),
        )

    conn.commit()
    conn.close()


def get_check_status(
    db_path: str, page_id: str, content_type: str
) -> Optional[Dict[str, Any]]:
    """取得檢查狀態"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM checks 
        WHERE page_id = ? AND content_type = ?
        ORDER BY id DESC LIMIT 1
    """,
        (page_id, content_type),
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def set_baseline_ready(db_path: str, page_id: str, content_type: str) -> None:
    """標記基準已建立"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE checks SET baseline_ready = 1
        WHERE page_id = ? AND content_type = ?
    """,
        (page_id, content_type),
    )
    conn.commit()
    conn.close()


def add_notifications(
    db_path: str,
    page_id: str,
    content_type: str,
    content_id: str,
    channels: List[Dict[str, Any]],
) -> List[str]:
    """為內容項目新增待通知（多個 channel）

    Args:
        db_path: 資料庫路徑
        page_id: 粉專 ID
        content_type: 內容類型
        content_id: 內容 ID
        channels: 通知管道設定清單

    Returns:
        成功新增的 channel_id 清單
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    added_channels = []

    for channel in channels:
        channel_id = channel.get("id")
        backend = channel.get("backend")

        try:
            cursor.execute(
                """
                INSERT INTO notifications 
                (page_id, content_type, content_id, channel_id, backend, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            """,
                (page_id, content_type, content_id, channel_id, backend),
            )
            added_channels.append(channel_id)
        except sqlite3.IntegrityError:
            # 已存在，不新增
            pass

    conn.commit()
    conn.close()
    return added_channels


def get_pending_notifications(
    db_path: str, channel_id: Optional[str] = None, limit: int = 50
) -> List[Dict[str, Any]]:
    """取得待發送通知

    Args:
        db_path: 資料庫路徑
        channel_id: 管道 ID 篩選
        limit: 最大返回數量

    Returns:
        待通知項目清單
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    now = datetime.now(timezone.utc).isoformat()

    if channel_id:
        cursor.execute(
            """
            SELECT n.*, i.summary, i.url, i.published_at
            FROM notifications n
            JOIN items i ON n.page_id = i.page_id 
                AND n.content_type = i.content_type 
                AND n.content_id = i.content_id
            WHERE n.status = 'pending' 
                AND n.channel_id = ?
                AND (n.next_retry_at IS NULL OR n.next_retry_at <= ?)
            ORDER BY n.id ASC
            LIMIT ?
        """,
            (channel_id, now, limit),
        )
    else:
        cursor.execute(
            """
            SELECT n.*, i.summary, i.url, i.published_at
            FROM notifications n
            JOIN items i ON n.page_id = i.page_id 
                AND n.content_type = i.content_type 
                AND n.content_id = i.content_id
            WHERE n.status = 'pending'
                AND (n.next_retry_at IS NULL OR n.next_retry_at <= ?)
            ORDER BY n.id ASC
            LIMIT ?
        """,
            (now, limit),
        )

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_notification_status(
    db_path: str,
    notification_id: int,
    status: str,
    error_message: Optional[str] = None,
    retry_key: Optional[str] = None,
) -> None:
    """更新通知狀態

    Args:
        db_path: 資料庫路徑
        notification_id: 通知 ID
        status: 狀態 ('sent', 'retry', 'failed')
        error_message: 錯誤訊息
        retry_key: 平台返回的重試鍵（如 LINE）
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    now = datetime.now(timezone.utc)

    if status == "sent":
        cursor.execute(
            """
            UPDATE notifications 
            SET status = ?, sent_at = ?, error_message = NULL,
                next_retry_at = NULL, retry_key = ?
            WHERE id = ?
        """,
            (status, now, retry_key, notification_id),
        )
    elif status == "retry":
        # 退避間隔：30 秒起跳，最高 1 小時
        # 依 attempts 指數退避
        cursor.execute(
            "SELECT attempts FROM notifications WHERE id = ?", (notification_id,)
        )
        row = cursor.fetchone()
        current_attempts = row[0] if row else 0

        # 計算下次重試時間：30 秒 * 2^attempts，最高 3600 秒（1 小時）
        backoff_seconds = min(30 * (2**current_attempts), 3600)
        next_retry = now + timedelta(seconds=backoff_seconds)

        cursor.execute(
            """
            UPDATE notifications 
            SET status = 'pending', attempts = attempts + 1,
                error_message = ?, next_retry_at = ?, retry_key = ?
            WHERE id = ?
        """,
            (error_message, next_retry.isoformat(), retry_key, notification_id),
        )
    elif status == "failed":
        cursor.execute(
            """
            UPDATE notifications
            SET status = 'failed', attempts = attempts + 1,
                error_message = ?, next_retry_at = NULL, retry_key = ?
            WHERE id = ?
        """,
            (error_message, retry_key, notification_id),
        )
    else:
        cursor.execute(
            """
            UPDATE notifications SET status = ? WHERE id = ?
        """,
            (status, notification_id),
        )

    conn.commit()
    conn.close()


def save_batch_with_transaction(
    db_path: str,
    new_items: List[Dict[str, Any]],
    notifications_to_add: List[Dict[str, Any]],
    check_updates: List[Dict[str, Any]],
    logger: logging.Logger,
) -> bool:
    """在一個 transaction 內保存新內容、通知與檢查狀態

    Args:
        db_path: 資料庫路徑
        new_items: 新內容項目清單
        notifications_to_add: 待新增通知清單
        check_updates: 檢查狀態更新清單
        logger: 日誌記錄器

    Returns:
        True 若成功，False 若失敗
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        # 保存新內容
        for item in new_items:
            try:
                cursor.execute(
                    """
                    INSERT INTO items 
                    (page_id, content_type, content_id, author_id, published_at, summary, url, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        item["page_id"],
                        item["content_type"],
                        item["content_id"],
                        item.get("author_id"),
                        (
                            item.get("published_at")
                            and item["published_at"].isoformat()
                            if item.get("published_at")
                            else None
                        ),
                        item.get("summary"),
                        item.get("url"),
                        item.get("raw_data"),
                    ),
                )
            except sqlite3.IntegrityError:
                # 已存在，跳過
                pass

        # 新增通知
        for notif in notifications_to_add:
            try:
                cursor.execute(
                    """
                    INSERT INTO notifications 
                    (page_id, content_type, content_id, channel_id, backend, status)
                    VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                    (
                        notif["page_id"],
                        notif["content_type"],
                        notif["content_id"],
                        notif["channel_id"],
                        notif.get("backend"),
                    ),
                )
            except sqlite3.IntegrityError:
                # 已存在，跳過
                pass

        # 更新檢查狀態
        now = datetime.now(timezone.utc)
        for check in check_updates:
            if "baseline_ready" in check:
                cursor.execute(
                    """
                    INSERT INTO checks
                    (page_id, content_type, baseline_ready, last_attempt_at,
                     last_success_at, status, error_code, error_message,
                     pagination_incomplete)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(page_id, content_type)
                    DO UPDATE SET
                        baseline_ready = excluded.baseline_ready,
                        last_attempt_at = excluded.last_attempt_at,
                        last_success_at = excluded.last_success_at,
                        status = excluded.status,
                        error_code = excluded.error_code,
                        error_message = excluded.error_message,
                        pagination_incomplete = excluded.pagination_incomplete
                """,
                    (
                        check["page_id"],
                        check["content_type"],
                        1 if check.get("baseline_ready") else 0,
                        now,
                        now if check["status"] == "success" else None,
                        check["status"],
                        check.get("error_code"),
                        check.get("error_message"),
                        1 if check.get("pagination_incomplete") else 0,
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO checks
                    (page_id, content_type, last_attempt_at, last_success_at, status,
                     error_code, error_message, pagination_incomplete)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(page_id, content_type)
                    DO UPDATE SET
                        last_attempt_at = excluded.last_attempt_at,
                        last_success_at = excluded.last_success_at,
                        status = excluded.status,
                        error_code = excluded.error_code,
                        error_message = excluded.error_message,
                        pagination_incomplete = excluded.pagination_incomplete
                """,
                    (
                        check["page_id"],
                        check["content_type"],
                        now,
                        now if check["status"] == "success" else None,
                        check["status"],
                        check.get("error_code"),
                        check.get("error_message"),
                        1 if check.get("pagination_incomplete") else 0,
                    ),
                )

        conn.commit()
        return True

    except Exception as e:
        logger.error(f"批次保存失敗：{e}")
        conn.rollback()
        return False
    finally:
        conn.close()
