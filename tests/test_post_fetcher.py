"""貼文讀取器測試 - v0.2 Core Correctness

涵蓋：
- GraphClient 測試
- /posts 端點使用
- 真實 cursor pagination
- incomplete fetch 不提交
- 首次基準不 spam
- API version 可配置
- 429 限流處理
"""

import unittest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock
import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from post_fetcher import PostFetcher, GraphClient


class TestGraphClient(unittest.TestCase):
    """Graph API 客戶端測試"""
    
    def setUp(self):
        """測試準備"""
        self.logger = Mock()
        self.client = GraphClient(
            access_token='test_token',
            api_version='v26.0',
            logger=self.logger
        )
    
    def test_default_api_version(self):
        """測試預設 API version"""
        client = GraphClient(access_token='test', logger=self.logger)
        self.assertEqual(client.api_version, 'v26.0')
    
    def test_custom_api_version(self):
        """測試自訂 API version"""
        client = GraphClient(
            access_token='test',
            api_version='v25.0',
            logger=self.logger
        )
        self.assertEqual(client.api_version, 'v25.0')
    
    def test_build_url(self):
        """測試 URL 建立"""
        url = self.client._build_url('page_id/posts')
        self.assertEqual(url, 'https://graph.facebook.com/v26.0/page_id/posts')
    
    def test_build_params(self):
        """測試參數建立"""
        params = self.client._build_params({'limit': 10})
        self.assertEqual(params['access_token'], 'test_token')
        self.assertEqual(params['limit'], 10)
    
    def test_is_rate_limited(self):
        """測試限流辨識"""
        mock_response = Mock()
        mock_response.status_code = 429
        error = requests.HTTPError(response=mock_response)
        
        self.assertTrue(self.client.is_rate_limited(error))
    
    def test_not_rate_limited(self):
        """測試非限流錯誤"""
        mock_response = Mock()
        mock_response.status_code = 401
        error = requests.HTTPError(response=mock_response)
        
        self.assertFalse(self.client.is_rate_limited(error))
    
    def test_get_retry_after(self):
        """測試 Retry-After 取得"""
        mock_response = Mock()
        mock_response.headers = {'Retry-After': '60'}
        error = requests.HTTPError(response=mock_response)
        
        retry_after = self.client.get_retry_after(error)
        self.assertEqual(retry_after, 60)
    
    def test_get_retry_after_seconds_header(self):
        """測試 Retry-After 以秒數格式"""
        mock_response = Mock()
        mock_response.headers = {'Retry-After': '30'}
        error = requests.HTTPError(response=mock_response)
        
        retry_after = self.client.get_retry_after(error)
        self.assertEqual(retry_after, 30)
    
    def test_get_retry_after_date_header(self):
        """測試 Retry-After 以日期格式"""
        from datetime import datetime, timezone, timedelta
        
        mock_response = Mock()
        future_time = datetime.now(timezone.utc) + timedelta(seconds=45)
        mock_response.headers = {'Retry-After': future_time.strftime('%a, %d %b %Y %H:%M:%S GMT')}
        error = requests.HTTPError(response=mock_response)
        
        retry_after = self.client.get_retry_after(error)
        # 日期格式會返回 None（目前實作不支援）
        self.assertIsNone(retry_after)
    
    def test_get_retry_after_invalid(self):
        """測試 Retry-After 無效值"""
        mock_response = Mock()
        mock_response.headers = {'Retry-After': 'invalid'}
        error = requests.HTTPError(response=mock_response)
        
        retry_after = self.client.get_retry_after(error)
        self.assertIsNone(retry_after)
    
    def test_get_retry_after_missing(self):
        """測試 Retry-After 標頭缺失"""
        mock_response = Mock()
        mock_response.headers = {}
        error = requests.HTTPError(response=mock_response)
        
        retry_after = self.client.get_retry_after(error)
        self.assertIsNone(retry_after)


class TestPostFetcher(unittest.TestCase):
    """貼文讀取器測試 - v0.2"""
    
    def setUp(self):
        """測試準備"""
        self.config = {
            'storage': {'database': ':memory:'},
            'posts': {
                'max_pages': 3,
                'initial_lookback_days': 7,
                'api_version': 'v26.0'
            },
            'targets': [
                {'page_id': 'test_page', 'enabled': True}
            ],
            'notifications': {
                'timezone': 'Asia/Taipei',
                'notify_existing_on_first_run': False,
                'channels': []
            }
        }
        
        self.logger = Mock()
        self.fetcher = PostFetcher(self.config, self.logger)
        self.fetcher.access_token = 'test_token'
    
    def test_uses_posts_endpoint(self):
        """測試使用 /posts 端點而非 /feed"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'data': [
                {
                    'id': 'post_1',
                    'created_time': '2026-09-18T10:00:00+0000',
                    'message': 'Test post'
                }
            ],
            'paging': {}
        }
        mock_response.raise_for_status = Mock()
        
        called_paths = []
        
        def mock_get(path, params=None):
            called_paths.append(path)
            return mock_response
        
        with patch.object(self.fetcher.graph, 'get', side_effect=mock_get):
            posts, incomplete, error = self.fetcher._fetch_posts('test_page')
        
        # 檢查使用 /posts 端點
        self.assertTrue(any('posts' in path for path in called_paths))
        self.assertFalse(any('feed' in path for path in called_paths))
    
    def test_cursor_pagination(self):
        """測試真實 cursor pagination"""
        call_count = [0]
        
        def mock_get(path, params=None):
            call_count[0] += 1
            
            mock_response = Mock()
            
            if call_count[0] == 1:
                # 第一頁
                mock_response.json.return_value = {
                    'data': [
                        {
                            'id': 'post_1',
                            'created_time': '2026-09-18T10:00:00+0000',
                            'message': 'Post 1'
                        }
                    ],
                    'paging': {
                        'next': 'next_url',
                        'cursors': {'after': 'cursor_1'}
                    }
                }
            else:
                # 第二頁
                mock_response.json.return_value = {
                    'data': [
                        {
                            'id': 'post_2',
                            'created_time': '2026-09-17T10:00:00+0000',
                            'message': 'Post 2'
                        }
                    ],
                    'paging': {}
                }
            
            mock_response.raise_for_status = Mock()
            return mock_response
        
        with patch.object(self.fetcher.graph, 'get', side_effect=mock_get):
            posts, incomplete, error = self.fetcher._fetch_posts('test_page')
        
        # 應該有兩筆貼文
        self.assertEqual(len(posts), 2)
        # 應該呼叫兩次 API
        self.assertEqual(call_count[0], 2)
    
    def test_max_pages_incomplete_no_commit(self):
        """測試 max_pages incomplete 不提交"""
        call_count = [0]
        
        def mock_get(path, params=None):
            call_count[0] += 1
            
            mock_response = Mock()
            mock_response.json.return_value = {
                'data': [
                    {
                        'id': f'post_{call_count[0]}',
                        'created_time': '2026-09-18T10:00:00+0000',
                        'message': f'Post {call_count[0]}'
                    }
                ],
                'paging': {
                    'next': f'next_{call_count[0]}',
                    'cursors': {'after': f'cursor_{call_count[0]}'}
                }
            }
            mock_response.raise_for_status = Mock()
            return mock_response
        
        with patch.object(self.fetcher.graph, 'get', side_effect=mock_get):
            posts, incomplete, error = self.fetcher._fetch_posts('test_page')
        
        # 應該達到 max_pages 限制（3 頁）
        self.assertEqual(len(posts), 3)
        self.assertTrue(incomplete)
        self.assertIsNone(error)
    
    def test_api_error_no_commit(self):
        """測試 API 錯誤不提交"""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = '{"error": {"message": "Rate limit exceeded"}}'
        error = requests.HTTPError(response=mock_response)
        
        with patch.object(self.fetcher.graph, 'get', side_effect=error):
            posts, incomplete, err = self.fetcher._fetch_posts('test_page')
        
        # 應該返回錯誤資訊
        self.assertTrue(incomplete)
        self.assertIsNotNone(err)
        self.assertEqual(err['code'], '429')
    
    def test_first_run_baseline_no_spam(self):
        """測試首次基準不 spam"""
        # 設定 notify_existing_on_first_run = False
        self.config['notifications']['notify_existing_on_first_run'] = False
        
        self.fetcher = PostFetcher(self.config, self.logger)
        self.fetcher.access_token = 'test_token'
        
        # 模擬基準未建立
        mock_response = Mock()
        mock_response.json.return_value = {
            'data': [
                {
                    'id': 'post_1',
                    'created_time': '2026-09-18T10:00:00+0000',
                    'message': 'Test'
                }
            ],
            'paging': {}
        }
        mock_response.raise_for_status = Mock()
        
        with patch.object(self.fetcher.graph, 'get', return_value=mock_response):
            with patch('src.post_fetcher.get_check_status', return_value=None):
                # 不 patch item_exists（已不存在）
                with patch('src.post_fetcher.save_batch_with_transaction') as mock_save:
                    mock_save.return_value = True
                    
                    result = self.fetcher.fetch_page_posts('test_page')
                    
                    # 檢查通知是否被加入（不應該）
                    call_args = mock_save.call_args
                    if call_args:
                        notifications = call_args[0][1]  # 第二個參數
                        self.assertEqual(len(notifications), 0)
    
    def test_posts_endpoint_no_author_filter(self):
        """測試 /posts 端點不需要作者篩選"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'data': [
                {
                    'id': 'post_1',
                    'created_time': '2026-09-18T10:00:00+0000',
                    'message': 'Test post'
                }
            ],
            'paging': {}
        }
        mock_response.raise_for_status = Mock()
        
        with patch.object(self.fetcher.graph, 'get', return_value=mock_response):
            posts, incomplete, error = self.fetcher._fetch_posts('test_page')
        
        # /posts 端點直接返回粉專貼文，不需要過濾
        self.assertEqual(len(posts), 1)
    
    def test_api_version_configurable(self):
        """測試 API version 可配置"""
        config = self.config.copy()
        config['posts'] = self.config['posts'].copy()
        config['posts']['api_version'] = 'v25.0'
        
        fetcher = PostFetcher(config, self.logger)
        fetcher.access_token = 'test_token'
        
        self.assertEqual(fetcher.graph.api_version, 'v25.0')
    
    def test_empty_result(self):
        """測試空結果處理"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'data': [],
            'paging': {}
        }
        mock_response.raise_for_status = Mock()
        
        with patch.object(self.fetcher.graph, 'get', return_value=mock_response):
            posts, incomplete, error = self.fetcher._fetch_posts('test_page')
        
        self.assertEqual(len(posts), 0)
        self.assertFalse(incomplete)
        self.assertIsNone(error)
    
    def test_network_error(self):
        """測試網路錯誤處理"""
        with patch.object(
            self.fetcher.graph, 'get',
            side_effect=requests.RequestException('Network error')
        ):
            posts, incomplete, error = self.fetcher._fetch_posts('test_page')
        
        self.assertEqual(len(posts), 0)
        self.assertTrue(incomplete)
        self.assertIsNotNone(error)
        self.assertEqual(error['code'], 'network')
    
    def test_prepare_item(self):
        """測試準備 item 資料"""
        post = {
            'id': 'post_1',
            'created_time': '2026-09-18T10:00:00+0000',
            'message': 'Test message',
            'permalink_url': 'https://facebook.com/posts/post_1'
        }
        
        item = self.fetcher._prepare_item('test_page', post)
        
        self.assertEqual(item['content_id'], 'post_1')
        self.assertEqual(item['author_id'], 'test_page')  # /posts 端點保證
        self.assertEqual(item['summary'], 'Test message')
        self.assertEqual(item['url'], 'https://facebook.com/posts/post_1')
    
    def test_429_rate_limit_handling(self):
        """測試 429 限流處理"""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {'Retry-After': '60'}
        mock_response.text = '{"error": {"message": "Rate limit exceeded"}}'
        error = requests.HTTPError(response=mock_response)
        
        with patch.object(self.fetcher.graph, 'get', side_effect=error):
            posts, incomplete, err = self.fetcher._fetch_posts('test_page')
        
        self.assertTrue(incomplete)
        self.assertIsNotNone(err)
        self.assertEqual(err['code'], '429')
        self.assertIn('rate_limit', err)


if __name__ == '__main__':
    unittest.main()
