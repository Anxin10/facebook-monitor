"""通知發送器模組

依設計文件第 3、8、9 節實作通知功能。
"""

import os
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from src.database import (
    get_pending_notifications, update_notification_status,
    get_items_by_page
)


class Notifier:
    """通知發送器
    
    支援多種通知管道：LINE、Telegram、Email、桌面通知
    """
    
    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """
        初始化通知發送器
        
        Args:
            config: 設定字典
            logger: 日誌記錄器
        """
        self.config = config
        self.logger = logger
        self.db_path = config.get('storage', {}).get('database', 'monitor.sqlite3')
        
        self.notifications_config = config.get('notifications', {})
        self.channel = self.notifications_config.get('channel', 'none')
    
    def send_pending(self) -> None:
        """發送所有待處理通知"""
        if self.channel == 'none':
            self.logger.debug("通知功能未啟用")
            return
        
        # 取得待發送通知
        pending = get_pending_notifications(self.db_path, channel=self.channel, limit=50)
        
        if not pending:
            self.logger.debug("無待發送通知")
            return
        
        self.logger.info(f"找到 {len(pending)} 則待發送通知")
        
        # 依管道發送
        if self.channel == 'line':
            self._send_via_line(pending)
        elif self.channel == 'telegram':
            self._send_via_telegram(pending)
        elif self.channel == 'email':
            self._send_via_email(pending)
        elif self.channel == 'desktop':
            self._send_via_desktop(pending)
        else:
            self.logger.warning(f"未知的通知管道：{self.channel}")
    
    def _build_message(self, notification: Dict[str, Any]) -> str:
        """建立通知訊息
        
        Args:
            notification: 通知項目（含內容資料）
            
        Returns:
            通知訊息字串
        """
        page_id = notification.get('page_id', 'Unknown')
        content_type = notification.get('content_type', 'unknown')
        content_id = notification.get('content_id', '')
        summary = notification.get('summary', '')
        url = notification.get('url', '')
        published_at = notification.get('published_at')
        
        # 內容類型文字
        type_text = '貼文' if content_type == 'post' else '限時動態' if content_type == 'story' else content_type
        
        # 時間格式化
        time_text = ''
        if published_at:
            try:
                dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                # 轉換到 Asia/Taipei
                from datetime import timezone as tz
                taipei_tz = tz(datetime.now().astimezone().utcoffset())
                dt_taipei = dt.astimezone(taipei_tz)
                time_text = f"發布時間：{dt_taipei.strftime('%Y/%m/%d %H:%M')}"
            except:
                time_text = f"發布時間：{published_at}"
        
        # 建立訊息
        message = f"🔔 Facebook 新內容通知\n"
        message += f"粉專：{page_id}\n"
        message += f"類型：{type_text}\n"
        
        if time_text:
            message += f"{time_text}\n"
        
        if summary:
            message += f"\n內容：{summary[:100]}\n"
        
        if url:
            message += f"\n連結：{url}\n"
        
        return message
    
    def _send_via_line(self, notifications: List[Dict[str, Any]]) -> None:
        """透過 LINE 發送通知"""
        import requests
        
        token = os.getenv('LINE_NOTIFY_TOKEN')
        if not token:
            self.logger.error("LINE Notify Token 未設定")
            return
        
        url = 'https://notify-api.line.me/api/notify'
        
        for notification in notifications:
            message = self._build_message(notification)
            
            try:
                response = requests.post(
                    url,
                    headers={'Authorization': f'Bearer {token}'},
                    data={'message': message},
                    timeout=10
                )
                response.raise_for_status()
                
                self.logger.info(f"LINE 通知發送成功：{notification.get('content_id')}")
                update_notification_status(
                    self.db_path, notification['id'], 'sent'
                )
                
            except Exception as e:
                self.logger.error(f"LINE 通知發送失敗：{e}")
                update_notification_status(
                    self.db_path, notification['id'], 'failed', str(e)
                )
    
    def _send_via_telegram(self, notifications: List[Dict[str, Any]]) -> None:
        """透過 Telegram 發送通知"""
        import requests
        
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not token or not chat_id:
            self.logger.error("Telegram Bot Token 或 Chat ID 未設定")
            return
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        
        for notification in notifications:
            message = self._build_message(notification)
            
            try:
                response = requests.post(
                    url,
                    json={
                        'chat_id': chat_id,
                        'text': message,
                        'parse_mode': 'HTML'
                    },
                    timeout=10
                )
                response.raise_for_status()
                
                self.logger.info(f"Telegram 通知發送成功：{notification.get('content_id')}")
                update_notification_status(
                    self.db_path, notification['id'], 'sent'
                )
                
            except Exception as e:
                self.logger.error(f"Telegram 通知發送失敗：{e}")
                update_notification_status(
                    self.db_path, notification['id'], 'failed', str(e)
                )
    
    def _send_via_email(self, notifications: List[Dict[str, Any]]) -> None:
        """透過 Email 發送通知"""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        smtp_host = os.getenv('EMAIL_SMTP_HOST')
        smtp_port = int(os.getenv('EMAIL_SMTP_PORT', 587))
        email_user = os.getenv('EMAIL_USER')
        email_password = os.getenv('EMAIL_PASSWORD')
        email_from = os.getenv('EMAIL_FROM')
        email_to = os.getenv('EMAIL_TO')
        
        if not all([smtp_host, email_user, email_password, email_from, email_to]):
            self.logger.error("Email 設定不完整")
            return
        
        # 合併多則通知為一封信
        messages = [self._build_message(n) for n in notifications]
        combined_message = '\n\n' + '-'*50 + '\n\n'.join(messages)
        
        try:
            msg = MIMEMultipart()
            msg['From'] = email_from
            msg['To'] = email_to
            msg['Subject'] = f"Facebook 新內容通知 ({len(notifications)}則)"
            msg.attach(MIMEText(combined_message, 'plain', 'utf-8'))
            
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(email_user, email_password)
                server.send_message(msg)
            
            self.logger.info(f"Email 通知發送成功：{len(notifications)}則")
            
            for notification in notifications:
                update_notification_status(
                    self.db_path, notification['id'], 'sent'
                )
                
        except Exception as e:
            self.logger.error(f"Email 通知發送失敗：{e}")
            for notification in notifications:
                update_notification_status(
                    self.db_path, notification['id'], 'failed', str(e)
                )
    
    def _send_via_desktop(self, notifications: List[Dict[str, Any]]) -> None:
        """透過桌面通知發送（僅支援部分平台）"""
        try:
            import plyer
            
            for notification in notifications:
                message = self._build_message(notification)
                
                try:
                    plyer.notification.notify(
                        title='Facebook 新內容通知',
                        message=message[:200],
                        timeout=10
                    )
                    self.logger.info(f"桌面通知發送成功：{notification.get('content_id')}")
                    update_notification_status(
                        self.db_path, notification['id'], 'sent'
                    )
                except Exception as e:
                    self.logger.error(f"桌面通知發送失敗：{e}")
                    update_notification_status(
                        self.db_path, notification['id'], 'failed', str(e)
                    )
                    
        except ImportError:
            self.logger.warning("plyer 未安裝，桌面通知不可用")
            self.logger.info("請執行：pip install plyer")
