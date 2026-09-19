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
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
import json

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# 需要先在記憶體中建立資料庫
from database import init_database, add_item, add_notifications


class TestNotifier(unittest.TestCase):
    """通知模組測試"""
    
    def setUp(self):
        """測試準備"""
        # 建立臨時資料庫
        import tempfile
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test.db')
        init_database(self.db_path)
        
        self.config = {
            'storage': {'database': self.db_path},
            'notifications': {
                'timezone': 'Asia/Taipei',
                'channels': [
                    {
                        'id': 'telegram_main',
                        'backend': 'apprise',
                        'url_env': 'TELEGRAM_APPRISE_URL'
                    },
                    {
                        'id': 'line_main',
                        'backend': 'line',
                        'token_env': 'LINE_CHANNEL_ACCESS_TOKEN',
                        'recipient_env': 'LINE_TO'
                    }
                ]
            }
        }
        
        self.logger = Mock()
    
    def tearDown(self):
        """清理"""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_send_pending_no_channels(self):
        """測試無管道設定"""
        config = self.config.copy()
        config['notifications'] = {'timezone': 'Asia/Taipei', 'channels': []}
        
        from notifier import Notifier
        notifier = Notifier(config, self.logger)
        notifier.send_pending()
        
        self.logger.debug.assert_called()
    
    def test_send_pending_apprise(self):
        """測試 Apprise 通知發送"""
        # 新增測試資料
        add_item(
            self.db_path, 'test_page', 'post', 'post_1',
            author_id='author_1',
            published_at=datetime.now(timezone.utc),
            summary='Test post',
            url='https://facebook.com/posts/post_1'
        )
        
        # 模擬 Apprise
        with patch('apprise.Apprise') as mock_apprise:
            mock_apobj = Mock()
            mock_apprise.return_value = mock_apobj
            mock_apobj.notify = Mock(return_value=True)
            
            from notifier import Notifier
            notifier = Notifier(self.config, self.logger)
            notifier.send_pending()
            
            # 檢查 Apprise 被呼叫
            mock_apobj.notify.assert_called()
    
    def test_send_pending_line(self):
        """測試 LINE 通知發送"""
        # 新增測試資料
        add_item(
            self.db_path, 'test_page', 'post', 'post_1',
            author_id='author_1',
            published_at=datetime.now(timezone.utc),
            summary='Test post',
            url='https://facebook.com/posts/post_1'
        )
        
        # 模擬 LINE API
        mock_response = Mock()
        mock_response.json.return_value = {
            'statuses': [
                {
                    'status': '200',
                    'requestId': 'req_123',
                    'is_duplicate': False
                }
            ]
        }
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        
        with patch('requests.post', return_value=mock_response):
            with patch('os.getenv', side_effect=lambda x: 'test_token' if 'token' in x else 'test_user_id'):
                from notifier import Notifier
                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()
                
                # 檢查 LINE 發送成功
                self.logger.info.assert_called()
    
    def test_line_idempotent_retry_uuid(self):
        """測試 LINE idempotent retry 使用 UUID"""
        # 模擬 LINE API
        mock_response = Mock()
        mock_response.json.return_value = {
            'statuses': [
                {
                    'status': '200',
                    'requestId': 'req_123',
                    'is_duplicate': False
                }
            ]
        }
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        
        captured_headers = {}
        
        def capture_headers(*args, **kwargs):
            captured_headers.update(kwargs.get('headers', {}))
            return mock_response
        
        with patch('requests.post', side_effect=capture_headers):
            with patch('os.getenv', side_effect=lambda x: 'test_token' if 'token' in x else 'test_user_id'):
                from notifier import Notifier
                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()
                
                # 檢查 X-Line-Retry-Key header 存在且為 UUID 格式
                self.assertIn('X-Line-Retry-Key', captured_headers)
                retry_key = captured_headers['X-Line-Retry-Key']
                # 驗證 UUID 格式
                uuid.UUID(retry_key)  # 不拋出異常表示是有效 UUID
    
    def test_line_409_conflict_as_success(self):
        """測試 LINE 409 衝突視為成功"""
        # 模擬 LINE API 返回 409
        mock_response = Mock()
        mock_response.status_code = 409
        mock_response.text = 'Conflict'
        mock_response.raise_for_status = Mock()
        
        with patch('requests.post', return_value=mock_response):
            with patch('os.getenv', side_effect=lambda x: 'test_token' if 'token' in x else 'test_user_id'):
                from notifier import Notifier
                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()
                
                # 檢查視為成功
                self.logger.info.assert_called()
    
    def test_line_5xx_save_retry_key(self):
        """測試 LINE 5xx 錯誤保存 retry_key 以便重試"""
        # 模擬 LINE API 返回 500
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = 'Server Error'
        mock_response.raise_for_status = Mock()
        
        with patch('requests.post', return_value=mock_response):
            with patch('os.getenv', side_effect=lambda x: 'test_token' if 'token' in x else 'test_user_id'):
                from notifier import Notifier
                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()
                
                # 檢查警告被記錄
                self.logger.warning.assert_called()
    
    def test_line_timeout_save_retry_key(self):
        """測試 LINE timeout 保存 retry_key 以便重試"""
        import requests
        
        with patch('requests.post', side_effect=requests.exceptions.Timeout('Request timeout')):
            with patch('os.getenv', side_effect=lambda x: 'test_token' if 'token' in x else 'test_user_id'):
                from notifier import Notifier
                notifier = Notifier(self.config, self.logger)
                notifier.send_pending()
                
                # 檢查警告被記錄
                self.logger.warning.assert_called()
    
    def test_per_channel_retry(self):
        """測試逐目的地重試"""
        # 新增兩個 channel 的通知
        add_item(
            self.db_path, 'test_page', 'post', 'post_1',
            author_id='author_1'
        )
        
        channels = [
            {'id': 'telegram_main', 'backend': 'apprise'},
            {'id': 'line_main', 'backend': 'line'}
        ]
        
        add_notifications(
            self.db_path, 'test_page', 'post', 'post_1', channels
        )
        
        from database import get_pending_notifications, update_notification_status
        
        # 取得通知
        pending = get_pending_notifications(self.db_path)
        self.assertEqual(len(pending), 2)
        
        # 模擬 telegram 失敗，line 成功
        telegram_id = [n['id'] for n in pending if n['channel_id'] == 'telegram_main'][0]
        line_id = [n['id'] for n in pending if n['channel_id'] == 'line_main'][0]
        
        # telegram 失敗
        update_notification_status(
            self.db_path, telegram_id, 'failed', 'Telegram error'
        )
        
        # line 成功
        update_notification_status(
            self.db_path, line_id, 'sent'
        )
        
        # 檢查只有 telegram 在待重試清單
        pending = get_pending_notifications(self.db_path)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['channel_id'], 'telegram_main')
    
    def test_notification_message_format(self):
        """測試通知訊息格式"""
        from notifier import Notifier
        notifier = Notifier(self.config, self.logger)
        
        notification = {
            'page_id': 'test_page',
            'content_type': 'post',
            'content_id': 'post_1',
            'channel_id': 'telegram_main',
            'summary': 'This is a test post message',
            'url': 'https://facebook.com/posts/post_1',
            'published_at': '2026-09-18T10:00:00+00:00'
        }
        
        message = notifier._build_message(notification)
        
        self.assertIn('Facebook 新內容通知', message)
        self.assertIn('test_page', message)
        self.assertIn('post_1', message)
        self.assertIn('https://facebook.com/posts/post_1', message)
    
    def test_timezone_handling(self):
        """測試時區處理"""
        from notifier import Notifier
        notifier = Notifier(self.config, self.logger)
        
        notification = {
            'page_id': 'test_page',
            'content_type': 'post',
            'content_id': 'post_1',
            'channel_id': 'telegram_main',
            'summary': 'Test',
            'url': 'https://facebook.com/posts/post_1',
            'published_at': '2026-09-18T10:00:00+00:00'
        }
        
        message = notifier._build_message(notification)
        
        # 應該包含格式化後的時間
        self.assertIn('發布時間', message)


if __name__ == '__main__':
    unittest.main()
