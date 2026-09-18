"""貼文讀取器模組

依設計文件第 2.1、3、5 節實作官方 API 讀取。
"""

import os
import logging
from typing import Any, Dict, List, Optional
import requests

from src.database import (
    add_item, item_exists, update_check_status, set_baseline_ready,
    get_check_status
)


class PostFetcher:
    """貼文讀取器
    
    使用 Facebook Graph API 讀取粉專貼文。
    """
    
    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """
        初始化貼文讀取器
        
        Args:
            config: 設定字典
            logger: 日誌記錄器
        """
        self.config = config
        self.logger = logger
        self.db_path = config.get('storage', {}).get('database', 'monitor.sqlite3')
        
        # API 設定
        self.app_id = os.getenv('FACEBOOK_APP_ID')
        self.access_token = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
        self.api_base = 'https://graph.facebook.com/v21.0'
        
        if not self.access_token:
            self.logger.error("缺少 Facebook Page Access Token")
    
    def fetch_all(self) -> None:
        """對所有啟用目標執行貼文讀取"""
        targets = self.config.get('targets', [])
        enabled_targets = [t for t in targets if t.get('enabled', False)]
        
        for target in enabled_targets:
            page_id = target.get('page_id')
            if not page_id:
                self.logger.warning(f"目標缺少 page_id: {target}")
                continue
            
            self.fetch_page_posts(page_id)
    
    def fetch_page_posts(self, page_id: str) -> List[Dict[str, Any]]:
        """讀取單一粉專的貼文
        
        Args:
            page_id: 粉專 ID
            
        Returns:
            新發現的貼文清單
        """
        self.logger.info(f"開始讀取粉專貼文：{page_id}")
        
        try:
            # 檢查上次狀態
            check_status = get_check_status(self.db_path, page_id, 'post')
            baseline_ready = check_status.get('baseline_ready', False) if check_status else False
            
            # 讀取貼文
            posts = self._fetch_feed(page_id)
            
            if not posts:
                self.logger.info(f"粉專 {page_id} 無貼文或讀取失敗")
                update_check_status(
                    self.db_path, page_id, 'post',
                    'failed', 'no_posts_or_error', '無貼文或讀取失敗'
                )
                return []
            
            # 處理新貼文
            new_posts = []
            for post in posts:
                content_id = post.get('id')
                if not content_id:
                    continue
                
                # 檢查是否已存在
                if not item_exists(self.db_path, page_id, 'post', content_id):
                    # 新增貼文
                    self._save_post(page_id, post)
                    new_posts.append(post)
                    self.logger.info(f"發現新貼文：{content_id}")
                else:
                    self.logger.debug(f"貼文已存在：{content_id}")
            
            # 更新檢查狀態
            update_check_status(
                self.db_path, page_id, 'post',
                'success', None, None
            )
            
            # 標記基準已建立（首次成功後）
            if not baseline_ready:
                set_baseline_ready(self.db_path, page_id, 'post')
                self.logger.info(f"粉專 {page_id} 貼文基準已建立")
            
            self.logger.info(f"粉專 {page_id} 貼文檢查完成，發現 {len(new_posts)} 則新貼文")
            return new_posts
            
        except Exception as e:
            self.logger.error(f"粉專 {page_id} 貼文讀取失敗：{e}")
            update_check_status(
                self.db_path, page_id, 'post',
                'failed', str(e)[:100], str(e)
            )
            return []
    
    def _fetch_feed(self, page_id: str) -> List[Dict[str, Any]]:
        """從 API 讀取貼文 feed
        
        Args:
            page_id: 粉專 ID
            
        Returns:
            貼文清單
        """
        posts = []
        params = {
            'access_token': self.access_token,
            'fields': 'id,author,created_time,message,story,full_picture,link,permalink_url,type,status_type',
            'limit': 25
        }
        
        max_pages = self.config.get('posts', {}).get('max_pages', 5)
        page = 0
        
        while page < max_pages:
            try:
                url = f"{self.api_base}/{page_id}/feed"
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                
                if 'data' not in data or not data['data']:
                    break
                
                # 篩選指定粉專發布的貼文
                for item in data['data']:
                    # 檢查作者是否為目標粉專
                    author = item.get('author', {})
                    author_id = author.get('id') if author else None
                    
                    if author_id == page_id:
                        posts.append(item)
                
                # 處理分頁
                paging = data.get('paging', {})
                if 'next' not in paging:
                    break
                
                # 使用 next 連結繼續讀取
                next_url = paging['next']
                # 移除參數中的 access_token 以避免洩漏
                next_url = next_url.replace(f'access_token={self.access_token}', 'ACCESS_TOKEN_PLACEHOLDER')
                next_url = next_url.replace('ACCESS_TOKEN_PLACEHOLDER', f'access_token={self.access_token}')
                
                response = requests.get(next_url, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                if 'data' not in data or not data['data']:
                    break
                
                for item in data['data']:
                    author = item.get('author', {})
                    author_id = author.get('id') if author else None
                    
                    if author_id == page_id:
                        posts.append(item)
                
                page += 1
                
            except requests.exceptions.RequestException as e:
                self.logger.error(f"API 請求失敗：{e}")
                break
            except Exception as e:
                self.logger.error(f"處理貼文失敗：{e}")
                break
        
        return posts
    
    def _save_post(self, page_id: str, post: Dict[str, Any]) -> None:
        """儲存貼文到資料庫
        
        Args:
            page_id: 粉專 ID
            post: 貼文資料
        """
        content_id = post.get('id')
        author_id = post.get('author', {}).get('id') if post.get('author') else None
        
        # 解析發布時間
        published_at = None
        created_time = post.get('created_time')
        if created_time:
            try:
                published_at = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
            except:
                pass
        
        # 建立摘要
        summary = self._build_summary(post)
        
        # 取得連結
        url = post.get('permalink_url') or post.get('link')
        
        # 儲存原始資料
        raw_data = self._to_json(post)
        
        add_item(
            self.db_path,
            page_id=page_id,
            content_type='post',
            content_id=content_id,
            author_id=author_id,
            published_at=published_at,
            summary=summary,
            url=url,
            raw_data=raw_data
        )
    
    def _build_summary(self, post: Dict[str, Any]) -> str:
        """建立貼文摘要
        
        Args:
            post: 貼文資料
            
        Returns:
            摘要文字
        """
        message = post.get('message', '')
        story = post.get('story', '')
        post_type = post.get('type', 'unknown')
        status_type = post.get('status_type', '')
        
        # 優先使用 message
        if message:
            return message[:200]  # 限制長度
        
        # 其次使用 story
        if story:
            return story[:200]
        
        # 依類型標示
        type_map = {
            'photo': '圖片貼文',
            'video': '影片貼文',
            'link': '連結分享',
            'status': '文字貼文',
            'shared_story': '分享內容'
        }
        return type_map.get(post_type, f'{post_type} 內容')
    
    def _to_json(self, obj: Any) -> str:
        """物件轉 JSON 字串
        
        Args:
            obj: 物件
            
        Returns:
            JSON 字串
        """
        import json
        return json.dumps(obj, ensure_ascii=False)
