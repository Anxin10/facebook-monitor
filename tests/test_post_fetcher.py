"""貼文讀取器測試

涵蓋：
- 作者篩選（from.id）
- 空結果處理
- 分頁游標
- API 錯誤處理
- 時間範圍查詢
"""

import unittest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock
import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from post_fetcher import PostFetcher


class TestPostFetcher(unittest.TestCase):
    """貼文讀取器測試"""
    
    def setUp(self):
        """測試準備"""
        self.config = {
            'storage': {'database': ':memory:'},
            'posts': {
                'max_pages': 3,
                'initial_lookback_days': 7
            },
            'targets': [
                {'page_id': 'test_page', 'enabled': True}
            ],
            'notifications': {'channels': []}
        }
        
        self.logger = Mock()
        self.fetcher = PostFetcher(self.config, self.logger)
        self.fetcher.access_token = 'test_token'
    
    def test_from_id_author_filter(self):
        """測試使用 from.id 判定作者"""
        # 模擬 API 回應
        mock_response = Mock()
        mock_response.json.return_value = {
            'data': [
                {
                    'id': 'post_1',
                    'from': {'id': 'test_page'},
                    'created_time': '2026-09-18T10:00:00+0000',
                    'message': 'Test post by page'
                },
                {
                    'id': 'post_2',
                    'from': {'id': 'other_page'},
                    'created_time': '2026-09-18T11:00:00+0000',
                    'message': 'Test post by other'
                }
            ],
            'paging': {}
        }
        mock_response.raise_for_status = Mock()
        
        with patch('requests.get', return_value=mock_response):
            posts, incomplete = self.fetcher._fetch_feed('test_page')
        
        # 應該只有一筆（作者的貼文）
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]['id'], 'post_1')
    
    def test_unknown_author_rejected(self):
        """測試未知作者被拒絕"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'data': [
                {
                    'id': 'post_1',
                    # 缺少 from
                    'created_time': '2026-09-18T10:00:00+0000',
                    'message': 'Test post'
                }
            ],
            'paging': {}
        }
        mock_response.raise_for_status = Mock()
        
        with patch('requests.get', return_value=mock_response):
            posts, incomplete = self.fetcher._fetch_feed('test_page')
        
        # 應該沒有貼文（作者未知）
        self.assertEqual(len(posts), 0)
    
    def test_empty_result(self):
        """測試空結果處理"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'data': [],
            'paging': {}
        }
        mock_response.raise_for_status = Mock()
        
        with patch('requests.get', return_value=mock_response):
            posts, incomplete = self.fetcher._fetch_feed('test_page')
        
        self.assertEqual(len(posts), 0)
        self.assertFalse(incomplete)
    
    def test_pagination_cursor(self):
        """測試分頁游標"""
        call_count = [0]
        
        def mock_get(url, params=None, timeout=None):
            call_count[0] += 1
            
            mock_response = Mock()
            
            if call_count[0] == 1:
                # 第一頁
                mock_response.json.return_value = {
                    'data': [
                        {
                            'id': 'post_1',
                            'from': {'id': 'test_page'},
                            'created_time': '2026-09-18T10:00:00+0000',
                            'message': 'Post 1'
                        }
                    ],
                    'paging': {
                        'next': 'https://graph.facebook.com/v21.0/test_page/feed?cursor=next'
                    }
                }
            else:
                # 第二頁
                mock_response.json.return_value = {
                    'data': [
                        {
                            'id': 'post_2',
                            'from': {'id': 'test_page'},
                            'created_time': '2026-09-17T10:00:00+0000',
                            'message': 'Post 2'
                        }
                    ],
                    'paging': {}
                }
            
            mock_response.raise_for_status = Mock()
            return mock_response
        
        with patch('requests.get', side_effect=mock_get):
            posts, incomplete = self.fetcher._fetch_feed('test_page')
        
        # 應該有兩筆貼文
        self.assertEqual(len(posts), 2)
        # 應該呼叫兩次 API
        self.assertEqual(call_count[0], 2)
    
    def test_pagination_limit(self):
        """測試分頁上限"""
        call_count = [0]
        
        def mock_get(url, params=None, timeout=None):
            call_count[0] += 1
            
            mock_response = Mock()
            mock_response.json.return_value = {
                'data': [
                    {
                        'id': f'post_{call_count[0]}',
                        'from': {'id': 'test_page'},
                        'created_time': '2026-09-18T10:00:00+0000',
                        'message': f'Post {call_count[0]}'
                    }
                ],
                'paging': {
                    'next': f'https://graph.facebook.com/v21.0/test_page/feed?page={call_count[0]}'
                }
            }
            mock_response.raise_for_status = Mock()
            return mock_response
        
        with patch('requests.get', side_effect=mock_get):
            posts, incomplete = self.fetcher._fetch_feed('test_page')
        
        # 應該達到 max_pages 限制（3 頁）
        self.assertEqual(len(posts), 3)
        self.assertTrue(incomplete)  # 分頁未完成
        self.assertEqual(call_count[0], 3)
    
    def test_api_rate_limit(self):
        """測試 API 限流處理"""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.raise_for_status = Mock(side_effect=requests.HTTPError(response=mock_response))
        
        with patch('requests.get', return_value=mock_response):
            posts, incomplete = self.fetcher._fetch_feed('test_page')
        
        # 應該返回空列表，標記未完成
        self.assertEqual(len(posts), 0)
        self.assertTrue(incomplete)
    
    def test_api_request_error(self):
        """測試 API 請求錯誤"""
        with patch('requests.get', side_effect=requests.RequestException('Network error')):
            posts, incomplete = self.fetcher._fetch_feed('test_page')
        
        self.assertEqual(len(posts), 0)
        self.assertTrue(incomplete)
    
    def test_fixed_graph_host(self):
        """測試使用固定 Graph host"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'data': [
                {
                    'id': 'post_1',
                    'from': {'id': 'test_page'},
                    'created_time': '2026-09-18T10:00:00+0000',
                    'message': 'Test'
                }
            ],
            'paging': {
                'next': 'https://graph.facebook.com/v21.0/test_page/feed?access_token=leaked_token'
            }
        }
        mock_response.raise_for_status = Mock()
        
        called_urls = []
        
        def mock_get(url, params=None, timeout=None):
            called_urls.append(url)
            return mock_response
        
        with patch('requests.get', side_effect=mock_get):
            posts, incomplete = self.fetcher._fetch_feed('test_page')
        
        # 檢查所有呼叫都使用固定 host
        for url in called_urls:
            self.assertTrue(url.startswith('https://graph.facebook.com/v21.0'))
            self.assertNotIn('leaked_token', url)
    
    def test_since_parameter(self):
        """測試 since 參數"""
        since_time = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        
        mock_response = Mock()
        mock_response.json.return_value = {
            'data': [],
            'paging': {}
        }
        mock_response.raise_for_status = Mock()
        
        called_params = []
        
        def mock_get(url, params=None, timeout=None):
            called_params.append(params)
            return mock_response
        
        with patch('requests.get', side_effect=mock_get):
            self.fetcher._fetch_feed('test_page', since_time)
        
        # 檢查 since 參數被傳遞
        self.assertEqual(len(called_params), 1)
        self.assertIn('since', called_params[0])
    
    def test_prepare_item(self):
        """測試準備 item 資料"""
        post = {
            'id': 'post_1',
            'from': {'id': 'test_page'},
            'created_time': '2026-09-18T10:00:00+0000',
            'message': 'Test message',
            'permalink_url': 'https://facebook.com/posts/post_1'
        }
        
        item = self.fetcher._prepare_item('test_page', post)
        
        self.assertEqual(item['content_id'], 'post_1')
        self.assertEqual(item['author_id'], 'test_page')
        self.assertEqual(item['summary'], 'Test message')
        self.assertEqual(item['url'], 'https://facebook.com/posts/post_1')
    
    def test_prepare_item_missing_author(self):
        """測試缺少作者的 item 被拒絕"""
        post = {
            'id': 'post_1',
            # 缺少 from
            'created_time': '2026-09-18T10:00:00+0000',
            'message': 'Test'
        }
        
        item = self.fetcher._prepare_item('test_page', post)
        
        self.assertIsNone(item)


if __name__ == '__main__':
    unittest.main()
