"""SQLite 資料庫模組

依設計文件第 6 節實作最小資料模型。
"""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """取得資料庫連接
    
    Args:
        db_path: 資料庫檔案路徑
        
    Returns:
        SQLite 連接物件
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_database(db_path: str) -> None:
    """初始化資料庫
    
    建立設計文件第 6 節定義的資料表：
    - targets: 監控對象
    - items: 內容及去重資料
    - checks: 各來源檢查狀態
    - notifications: 待通知與重試紀錄
    
    Args:
        db_path: 資料庫檔案路徑
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    # targets 表：監控對象
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS targets (
            page_id TEXT PRIMARY KEY,
            url TEXT,
            account_type TEXT DEFAULT 'page_assumed',
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # items 表：內容及去重資料
    # 唯一鍵為 (page_id, content_type, content_id)
    cursor.execute('''
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
    ''')
    
    # 建立索引加速查詢
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_items_page_id 
        ON items(page_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_items_first_seen_at 
        ON items(first_seen_at)
    ''')
    
    # checks 表：各來源檢查狀態
    cursor.execute('''
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
            UNIQUE(page_id, content_type)
        )
    ''')
    
    # notifications 表：待通知與重試紀錄
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id TEXT NOT NULL,
            content_type TEXT NOT NULL,
            content_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            attempts INTEGER DEFAULT 0,
            next_retry_at TIMESTAMP,
            sent_at TIMESTAMP,
            error_message TEXT,
            UNIQUE(page_id, content_type, content_id, channel)
        )
    ''')
    
    # 建立索引
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_notifications_status 
        ON notifications(status)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_notifications_next_retry 
        ON notifications(next_retry_at)
    ''')
    
    conn.commit()
    conn.close()
    logging.info(f"資料庫初始化完成：{db_path}")


def add_or_update_target(
    db_path: str,
    page_id: str,
    url: str,
    account_type: str = 'page_assumed',
    enabled: bool = True
) -> None:
    """新增或更新監控目標
    
    Args:
        db_path: 資料庫路徑
        page_id: 粉專 ID
        url: 粉專網址
        account_type: 帳號類型
        enabled: 是否啟用
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO targets 
        (page_id, url, account_type, enabled, updated_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (page_id, url, account_type, 1 if enabled else 0, datetime.now(timezone.utc)))
    
    conn.commit()
    conn.close()


def get_enabled_targets(db_path: str) -> List[Dict[str, Any]]:
    """取得所有啟用的監控目標
    
    Args:
        db_path: 資料庫路徑
        
    Returns:
        目標清單
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM targets WHERE enabled = 1')
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
    raw_data: Optional[str] = None
) -> Optional[str]:
    """新增內容項目
    
    Args:
        db_path: 資料庫路徑
        page_id: 粉專 ID
        content_type: 內容類型 ('post' 或 'story')
        content_id: 內容 ID
        author_id: 作者 ID
        published_at: 發布時間
        summary: 摘要
        url: 連結
        raw_data: 原始資料 JSON
        
    Returns:
        內容 ID 若成功新增，否則 None（已存在）
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO items 
            (page_id, content_type, content_id, author_id, published_at, summary, url, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (page_id, content_type, content_id, author_id, 
              published_at.isoformat() if published_at else None,
              summary, url, raw_data))
        conn.commit()
        return content_id
    except sqlite3.IntegrityError:
        # 已存在，不新增
        return None
    finally:
        conn.close()


def item_exists(db_path: str, page_id: str, content_type: str, content_id: str) -> bool:
    """檢查內容是否已存在
    
    Args:
        db_path: 資料庫路徑
        page_id: 粉專 ID
        content_type: 內容類型
        content_id: 內容 ID
        
    Returns:
        True 若存在
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 1 FROM items 
        WHERE page_id = ? AND content_type = ? AND content_id = ?
    ''', (page_id, content_type, content_id))
    
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def get_items_by_page(
    db_path: str,
    page_id: str,
    content_type: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """取得指定粉專的內容項目
    
    Args:
        db_path: 資料庫路徑
        page_id: 粉專 ID
        content_type: 內容類型篩選
        limit: 最大返回數量
        
    Returns:
        內容項目清單
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    if content_type:
        cursor.execute('''
            SELECT * FROM items 
            WHERE page_id = ? AND content_type = ?
            ORDER BY first_seen_at DESC
            LIMIT ?
        ''', (page_id, content_type, limit))
    else:
        cursor.execute('''
            SELECT * FROM items 
            WHERE page_id = ?
            ORDER BY first_seen_at DESC
            LIMIT ?
        ''', (page_id, limit))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_check_status(
    db_path: str,
    page_id: str,
    content_type: str,
    status: str,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None
) -> None:
    """更新檢查狀態
    
    Args:
        db_path: 資料庫路徑
        page_id: 粉專 ID
        content_type: 內容類型
        status: 狀態 ('success', 'failed', 'rate_limited', 'auth_error')
        error_code: 錯誤代碼
        error_message: 錯誤訊息
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    now = datetime.now(timezone.utc)
    
    cursor.execute('''
        INSERT INTO checks 
        (page_id, content_type, last_attempt_at, last_success_at, status, error_code, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(page_id, content_type) 
        DO UPDATE SET 
            last_attempt_at = excluded.last_attempt_at,
            last_success_at = CASE WHEN excluded.status = 'success' THEN excluded.last_success_at ELSE checks.last_success_at END,
            status = excluded.status,
            error_code = excluded.error_code,
            error_message = excluded.error_message
    ''', (page_id, content_type, now, 
          now if status == 'success' else None,
          status, error_code, error_message))
    
    conn.commit()
    conn.close()


def get_check_status(db_path: str, page_id: str, content_type: str) -> Optional[Dict[str, Any]]:
    """取得檢查狀態
    
    Args:
        db_path: 資料庫路徑
        page_id: 粉專 ID
        content_type: 內容類型
        
    Returns:
        狀態記錄或 None
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM checks 
        WHERE page_id = ? AND content_type = ?
        ORDER BY id DESC LIMIT 1
    ''', (page_id, content_type))
    
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None


def set_baseline_ready(db_path: str, page_id: str, content_type: str) -> None:
    """標記基準已建立
    
    Args:
        db_path: 資料庫路徑
        page_id: 粉專 ID
        content_type: 內容類型
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE checks SET baseline_ready = 1
        WHERE page_id = ? AND content_type = ?
    ''', (page_id, content_type))
    
    conn.commit()
    conn.close()


def add_notification(
    db_path: str,
    page_id: str,
    content_type: str,
    content_id: str,
    channel: str
) -> bool:
    """新增待通知項目
    
    Args:
        db_path: 資料庫路徑
        page_id: 粉專 ID
        content_type: 內容類型
        content_id: 內容 ID
        channel: 通知管道
        
    Returns:
        True 若成功新增，False 若已存在
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO notifications 
            (page_id, content_type, content_id, channel, status)
            VALUES (?, ?, ?, ?, 'pending')
        ''', (page_id, content_type, content_id, channel))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_pending_notifications(
    db_path: str,
    channel: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """取得待發送通知
    
    Args:
        db_path: 資料庫路徑
        channel: 管道篩選
        limit: 最大返回數量
        
    Returns:
        待通知項目清單
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    if channel:
        cursor.execute('''
            SELECT n.*, i.summary, i.url, i.published_at
            FROM notifications n
            JOIN items i ON n.page_id = i.page_id 
                AND n.content_type = i.content_type 
                AND n.content_id = i.content_id
            WHERE n.status = 'pending' 
                AND n.channel = ?
                AND (n.next_retry_at IS NULL OR n.next_retry_at <= ?)
            ORDER BY n.id ASC
            LIMIT ?
        ''', (channel, datetime.now(timezone.utc).isoformat(), limit))
    else:
        cursor.execute('''
            SELECT n.*, i.summary, i.url, i.published_at
            FROM notifications n
            JOIN items i ON n.page_id = i.page_id 
                AND n.content_type = i.content_type 
                AND n.content_id = i.content_id
            WHERE n.status = 'pending'
                AND (n.next_retry_at IS NULL OR n.next_retry_at <= ?)
            ORDER BY n.id ASC
            LIMIT ?
        ''', (datetime.now(timezone.utc).isoformat(), limit))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_notification_status(
    db_path: str,
    notification_id: int,
    status: str,
    error_message: Optional[str] = None
) -> None:
    """更新通知狀態
    
    Args:
        db_path: 資料庫路徑
        notification_id: 通知 ID
        status: 狀態 ('pending', 'sent', 'failed')
        error_message: 錯誤訊息
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    if status == 'sent':
        cursor.execute('''
            UPDATE notifications 
            SET status = ?, sent_at = ?
            WHERE id = ?
        ''', (status, datetime.now(timezone.utc), notification_id))
    elif status == 'failed':
        cursor.execute('''
            UPDATE notifications 
            SET status = ?, attempts = attempts + 1,
                error_message = ?,
                next_retry_at = ?
            WHERE id = ?
        ''', (status, error_message, 
              datetime.now(timezone.utc).replace(
                  minute=0, second=0, microsecond=0
              ).replace(hour=(datetime.now(timezone.utc).hour + 1) % 24),
              notification_id))
    else:
        cursor.execute('''
            UPDATE notifications SET status = ? WHERE id = ?
        ''', (status, notification_id))
    
    conn.commit()
    conn.close()
