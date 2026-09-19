"""通知發送器模組

依 v0.2 實作多管道通知功能。
支援 Apprise（Telegram、Email 等）與 LINE Messaging API。
每個 channel id 獨立追蹤送達與重試。
LINE 支援冪等重試（idempotent retry）。
"""

import os
import uuid
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

try:
    import apprise

    APPRISE_AVAILABLE = True
except ImportError:
    APPRISE_AVAILABLE = False

from src.database import get_pending_notifications, update_notification_status


class Notifier:
    """通知發送器

    支援多種通知管道：
    - Apprise: Telegram, Email, 等
    - LINE: Messaging API push（支援冪等重試）
    """

    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """初始化通知發送器"""
        self.config = config
        self.logger = logger
        self.db_path = config.get("storage", {}).get("database", "monitor.sqlite3")

        self.notifications_config = config.get("notifications", {})
        self.channels = self.notifications_config.get("channels", [])
        self.timezone_name = self.notifications_config.get("timezone", "Asia/Taipei")

    def send_pending(self) -> None:
        """發送所有待處理通知，依 channel_id 分別處理"""
        if not self.channels:
            self.logger.debug("通知管道未設定")
            return

        # 依 channel_id 分別取得待發送通知
        for channel_config in self.channels:
            channel_id = channel_config.get("id")
            backend = channel_config.get("backend")

            if not channel_id:
                self.logger.warning("通知管道缺少 id 設定")
                continue

            # 取得該 channel 的待發送通知
            pending = get_pending_notifications(
                self.db_path, channel_id=channel_id, limit=50
            )

            if not pending:
                self.logger.debug(f"Channel {channel_id}: 無待發送通知")
                continue

            self.logger.info(f"Channel {channel_id}: 找到 {len(pending)} 則待發送通知")

            # 依後端發送
            if backend == "apprise":
                self._send_via_apprise(channel_config, pending)
            elif backend == "line":
                self._send_via_line(channel_config, pending)
            else:
                self.logger.warning(f"Channel {channel_id}: 未知的後端 {backend}")

    def _build_message(self, notification: Dict[str, Any]) -> str:
        """建立通知訊息"""
        page_id = notification.get("page_id", "Unknown")
        content_type = notification.get("content_type", "unknown")
        content_id = notification.get("content_id", "")
        summary = notification.get("summary", "")
        url = notification.get("url", "")
        published_at = notification.get("published_at")

        # 內容類型文字
        type_text = (
            "貼文"
            if content_type == "post"
            else "限時動態" if content_type == "story" else content_type
        )

        # 時間格式化（使用設定時區）
        time_text = ""
        if published_at:
            try:
                from zoneinfo import ZoneInfo

                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                tz = ZoneInfo(self.timezone_name)
                dt_local = dt.astimezone(tz)
                time_text = f"發布時間：{dt_local.strftime('%Y/%m/%d %H:%M')}"
            except Exception as e:
                self.logger.debug(f"時間格式化失敗：{e}")
                time_text = f"發布時間：{published_at}"

        # 建立訊息
        message = f"🔔 Facebook 新內容通知\n"
        message += f"粉專：{page_id}\n"
        message += f"類型：{type_text}\n"

        if time_text:
            message += f"{time_text}\n"

        if summary:
            message += f"\n內容：{summary[:200]}\n"

        if url:
            message += f"\n連結：{url}\n"

        return message

    def _send_via_apprise(
        self, channel_config: Dict[str, Any], notifications: List[Dict[str, Any]]
    ) -> None:
        """透過 Apprise 發送通知（Telegram、Email 等）"""
        if not APPRISE_AVAILABLE:
            self.logger.error("Apprise 未安裝，請執行：pip install apprise")
            return

        url_env = channel_config.get("url_env")
        if not url_env:
            self.logger.error(f"Apprise 管道缺少 url_env 設定")
            return

        apprise_url = os.getenv(url_env)
        if not apprise_url:
            self.logger.error(f"環境變數 {url_env} 未設定")
            return

        # 建立 Apprise 物件
        try:
            ap = apprise.Apprise()
            ap.add(apprise_url)
        except Exception as e:
            self.logger.error(f"Apprise 初始化失敗：{e}")
            return

        # 逐則發送（每則獨立追蹤狀態）
        for notification in notifications:
            message = self._build_message(notification)

            try:
                result = ap.notify(body=message, title="Facebook 新內容通知")

                if result:
                    self.logger.info(
                        f"Apprise 通知發送成功：{notification.get('content_id')}"
                    )
                    update_notification_status(self.db_path, notification["id"], "sent")
                else:
                    self.logger.error(
                        f"Apprise 通知發送失敗（無回應）：{notification.get('content_id')}"
                    )
                    update_notification_status(
                        self.db_path, notification["id"], "failed", "Apprise 返回失敗"
                    )

            except Exception as e:
                self.logger.error(f"Apprise 通知發送異常：{e}")
                update_notification_status(
                    self.db_path, notification["id"], "failed", str(e)
                )

    def _send_via_line(
        self, channel_config: Dict[str, Any], notifications: List[Dict[str, Any]]
    ) -> None:
        """透過 LINE Messaging API 發送通知

        支援冪等重試（idempotent retry）：
        - 使用 UUID 作為 X-Line-Retry-Key
        - 從資料庫讀取已存儲的 retry_key（重試時沿用）
        - 409 衝突視為已成功接受
        - timeout/5xx 時沿用相同 UUID 重試
        """
        import requests

        token_env = channel_config.get("token_env")
        recipient_env = channel_config.get("recipient_env")

        if not token_env or not recipient_env:
            self.logger.error("LINE 管道缺少 token_env 或 recipient_env 設定")
            return

        channel_token = os.getenv(token_env)
        recipient = os.getenv(recipient_env)

        if not channel_token or not recipient:
            self.logger.error(f"環境變數 {token_env} 或 {recipient_env} 未設定")
            return

        url = "https://api.line.me/v2/bot/message/push"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {channel_token}",
        }

        # 逐則發送（每則獨立追蹤狀態）
        for notification in notifications:
            message = self._build_message(notification)

            payload = {"to": recipient, "messages": [{"type": "text", "text": message}]}

            # 從資料庫讀取已存儲的 retry_key（重試時沿用）
            retry_key = notification.get("retry_key")

            # 如果沒有 retry_key，生成新的 UUID
            if not retry_key:
                retry_key = str(uuid.uuid4())

            # 加入 X-Line-Retry-Key header
            headers["X-Line-Retry-Key"] = retry_key

            try:
                response = requests.post(url, json=payload, headers=headers, timeout=10)

                # 任何 2xx 都表示 LINE Platform 已接受請求，不應再重試。
                if 200 <= response.status_code < 300:
                    self.logger.info(
                        f"LINE 通知發送成功：{notification.get('content_id')}"
                    )
                    update_notification_status(
                        self.db_path,
                        notification["id"],
                        "sent",
                        retry_key=retry_key,
                    )

                # 409 衝突視為已成功接受（冪等）
                elif response.status_code == 409:
                    self.logger.info(
                        f"LINE 通知 409 衝突（視為成功）：{notification.get('content_id')}"
                    )
                    update_notification_status(
                        self.db_path, notification["id"], "sent", retry_key=retry_key
                    )

                # 5xx 伺服器錯誤：保存 retry_key 以便重試沿用
                elif 500 <= response.status_code < 600:
                    error_msg = (
                        f"LINE API 5xx 錯誤：{response.status_code}: {response.text}"
                    )
                    self.logger.warning(f"LINE 通知伺服器錯誤：{error_msg}")
                    update_notification_status(
                        self.db_path,
                        notification["id"],
                        "failed",
                        f"5xx 伺服器錯誤：{response.text}",
                        retry_key=retry_key,
                    )

                # 其他錯誤
                else:
                    error_msg = f"LINE API 返回 {response.status_code}: {response.text}"
                    self.logger.error(f"LINE 通知發送失敗：{error_msg}")
                    update_notification_status(
                        self.db_path,
                        notification["id"],
                        "permanent_failed",
                        error_msg,
                        retry_key=retry_key,
                    )

            except requests.exceptions.Timeout:
                # timeout：保存 retry_key 以便重試沿用
                self.logger.warning(f"LINE 通知超時：{notification.get('content_id')}")
                update_notification_status(
                    self.db_path,
                    notification["id"],
                    "failed",
                    "請求超時",
                    retry_key=retry_key,
                )
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"LINE 通知請求失敗，將重試：{e}")
                update_notification_status(
                    self.db_path,
                    notification["id"],
                    "failed",
                    str(e),
                    retry_key=retry_key,
                )
            except Exception as e:
                self.logger.error(f"LINE 通知發送異常：{e}")
                update_notification_status(
                    self.db_path, notification["id"], "failed", str(e)
                )
