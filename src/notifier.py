"""通知發送器模組

依 HYBRID_INTEGRATION.md 實作多管道通知功能。
支援 Apprise（Telegram、Email 等）與 LINE Messaging API。
每個 channel id 獨立追蹤送達與重試。
"""

import os
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

try:
    import apprise
    APPRISE_AVAILABLE = True
except ImportError:
    APPRISE_AVAILABLE = False

from src.database import (
    get_pending_notifications, update_notification_status
)


class Notifier:
    """通知發送器
    
    支援多種通知管道：
    - Apprise: Telegram, Email, 等
    - LINE: Messaging API push
    """
    
    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """初始化通知發送器"""
        self.config = config
        self.logger = logger
        self.db_path = config.get('storage', {}).get('database', 'monitor.sqlite3')
        
        self.notifications_config = config.get('notifications', {})
        self.channels = self.notifications_config.get('channels', [])
        self.timezone_name = self.notifications_config.get('timezone', 'Asia/Taipei')
    
    def send_pending(self) -> None:
        """發送所有待處理通知，依 channel_id 分別處理"""
        if not self.channels:
            self.logger.debug("通知管道未設定")
            return
        
        # 依 channel_id 分別取得待發送通知
        for channel_config in self.channels:
            channel_id = channel_config.get('id')
            backend = channel_config.get('backend')
            
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
            if backend == 'apprise':
                self._send_via_apprise(channel_config, pending)
            elif backend == 'line':
                self._send_via_line(channel_config, pending)
            else:
                self.logger.warning(f"Channel {channel_id}: 未知的後端 {backend}")
    
    def _build_message(self, notification: Dict[str, Any]) -> str:
        """建立通知訊息"""
        page_id = notification.get('page_id', 'Unknown')
        content_type = notification.get('content_type', 'unknown')
        content_id = notification.get('content_id', '')
        summary = notification.get('summary', '')
        url = notification.get('url', '')
        published_at = notification.get('published_at')
        
        # 內容類型文字
        type_text = '貼文' if content_type == 'post' else '限時動態' if content_type == 'story' else content_type
        
        # 時間格式化（使用設定時區）
        time_text = ''
        if published_at:
            try:
                from zoneinfo import ZoneInfo
                dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
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
        
        url_env = channel_config.get('url_env')
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
                result = ap.notify(
                    body=message,
                    title='Facebook 新內容通知'
                )
                
                if result:
                    self.logger.info(
                        f"Apprise 通知發送成功：{notification.get('content_id')}"
                    )
                    update_notification_status(
                        self.db_path, notification['id'], 'sent'
                    )
                else:
                    self.logger.error(
                        f"Apprise 通知發送失敗（無回應）：{notification.get('content_id')}"
                    )
                    update_notification_status(
                        self.db_path, notification['id'], 'failed',
                        'Apprise 返回失敗'
                    )
                    
            except Exception as e:
                self.logger.error(f"Apprise 通知發送異常：{e}")
                update_notification_status(
                    self.db_path, notification['id'], 'failed', str(e)
                )
    
    def _send_via_line(
        self, channel_config: Dict[str, Any], notifications: List[Dict[str, Any]]
    ) -> None:
        """透過 LINE Messaging API 發送通知"""
        import requests
        
        token_env = channel_config.get('token_env')
        recipient_env = channel_config.get('recipient_env')
        
        if not token_env or not recipient_env:
            self.logger.error("LINE 管道缺少 token_env 或 recipient_env 設定")
            return
        
        channel_token = os.getenv(token_env)
        recipient = os.getenv(recipient_env)
        
        if not channel_token or not recipient:
            self.logger.error(f"環境變數 {token_env} 或 {recipient_env} 未設定")
            return
        
        url = 'https://api.line.me/v2/bot/message/push'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {channel_token}'
        }
        
        # 逐則發送（每則獨立追蹤狀態）
        for notification in notifications:
            message = self._build_message(notification)
            
            payload = {
                'to': recipient,
                'messages': [{
                    'type': 'text',
                    'text': message
                }]
            }
            
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=10)
                
                # LINE API 成功時返回 200 與 responseId
                if response.status_code == 200:
                    response_data = response.json()
                    retry_key = response_data.get('responseId')
                    
                    self.logger.info(
                        f"LINE 通知發送成功：{notification.get('content_id')}"
                    )
                    update_notification_status(
                        self.db_path, notification['id'], 'sent',
                        retry_key=retry_key
                    )
                else:
                    error_msg = f"LINE API 返回 {response.status_code}: {response.text}"
                    self.logger.error(f"LINE 通知發送失敗：{error_msg}")
                    update_notification_status(
                        self.db_path, notification['id'], 'failed', error_msg
                    )
                    
            except requests.exceptions.RequestException as e:
                self.logger.error(f"LINE 通知請求失敗：{e}")
                update_notification_status(
                    self.db_path, notification['id'], 'failed', str(e)
                )
            except Exception as e:
                self.logger.error(f"LINE 通知發送異常：{e}")
                update_notification_status(
                    self.db_path, notification['id'], 'failed', str(e)
                )
