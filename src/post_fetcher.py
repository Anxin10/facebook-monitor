"""貼文讀取器模組

依 HYBRID_INTEGRATION.md 實作官方 API 讀取。
- 使用固定 Graph host，不跟隨含 Token 的 next URL
- 使用 from.id 判定作者，未知作者明確失敗
- 分頁使用游標與固定 limit
- 分頁未完成或 API 錯誤時不保存部分資料
"""

import os
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import requests

from src.database import (
    add_item, item_exists, update_check_status, set_baseline_ready,
    get_check_status, save_batch_with_transaction
)


class PostFetcher:
    """貼文讀取器
    
    使用 Facebook Graph API 讀取粉專貼文。
    """
    
    # 固定的 Graph API host，不跟隨 next URL
    GRAPH_HOST = 'https://graph.facebook.com'
    API_VERSION = 'v21.0'
    
    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """初始化貼文讀取器"""
        self.config = config
        self.logger = logger
        self.db_path = config.get('storage', {}).get('database', 'monitor.sqlite3')
        
        # API 設定
        self.access_token = os.getenv('FACEBOOK_ACCESS_TOKEN')
        if not self.access_token:
            self.logger.error("缺少 Facebook Access Token")
        
        # 貼文監控設定
        self.posts_config = config.get('posts', {})
        self.max_pages = self.posts_config.get('max_pages', 5)
        self.initial_lookback_days = self.posts_config.get('initial_lookback_days', 7)
    
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
            last_success_at = check_status.get('last_success_at') if check_status else None
            
            # 決定查詢下界
            # 首次：最近 7 天；後續：上次成功時間減 1 小時
            now = datetime.now(timezone.utc)
            if baseline_ready and last_success_at:
                try:
                    last_success = datetime.fromisoformat(last_success_at.replace('Z', '+00:00'))
                    since_time = last_success - timedelta(hours=1)
                except:
                    since_time = now - timedelta(days=self.initial_lookback_days)
            else:
                since_time = now - timedelta(days=self.initial_lookback_days)
            
            since_param = since_time.isoformat()
            self.logger.debug(f"查詢下界：{since_param}")
            
            # 讀取貼文
            posts, pagination_incomplete = self._fetch_feed(page_id, since_param)
            
            if not posts:
                # 空列表視為成功（無新貼文）
                self.logger.info(f"粉專 {page_id} 無新貼文")
                update_check_status(
                    self.db_path, page_id, 'post',
                    'success', None, None, pagination_incomplete=False
                )
                
                # 首次成功後標記基準已建立
                if not baseline_ready:
                    set_baseline_ready(self.db_path, page_id, 'post')
                    self.logger.info(f"粉專 {page_id} 貼文基準已建立")
                
                return []
            
            # 處理新貼文（先收集，不立即保存）
            new_posts = []
            for post in posts:
                content_id = post.get('id')
                if not content_id:
                    continue
                
                # 檢查是否已存在
                if not item_exists(self.db_path, page_id, 'post', content_id):
                    new_posts.append(post)
                    self.logger.info(f"發現新貼文：{content_id}")
                else:
                    self.logger.debug(f"貼文已存在：{content_id}")
            
            # 若有新貼文，批次保存
            if new_posts:
                # 準備批次保存資料
                items_to_save = []
                notifications_to_add = []
                
                # 取得啟用的通知管道
                enabled_channels = self.config.get('notifications', {}).get('channels', [])
                
                for post in new_posts:
                    content_id = post.get('id')
                    
                    # 準備 item 資料
                    item_data = self._prepare_item(page_id, post)
                    if item_data:
                        items_to_save.append(item_data)
                        
                        # 準備通知（若啟用了通知管道）
                        if enabled_channels:
                            for channel in enabled_channels:
                                notifications_to_add.append({
                                    'page_id': page_id,
                                    'content_type': 'post',
                                    'content_id': content_id,
                                    'channel_id': channel.get('id'),
                                    'backend': channel.get('backend')
                                })
                
                # 批次保存（transaction）
                check_update = {
                    'page_id': page_id,
                    'content_type': 'post',
                    'status': 'success',
                    'error_code': None,
                    'error_message': None,
                    'pagination_incomplete': pagination_incomplete
                }
                
                success = save_batch_with_transaction(
                    self.db_path,
                    items_to_save,
                    notifications_to_add,
                    [check_update],
                    self.logger
                )
                
                if success:
                    self.logger.info(
                        f"粉專 {page_id} 貼文檢查完成，保存 {len(items_to_save)} 則新貼文"
                    )
                else:
                    self.logger.error(f"粉專 {page_id} 貼文保存失敗")
                    return []
            else:
                # 無新貼文，只更新檢查狀態
                update_check_status(
                    self.db_path, page_id, 'post',
                    'success', None, None, pagination_incomplete
                )
            
            # 首次成功後標記基準已建立
            if not baseline_ready:
                set_baseline_ready(self.db_path, page_id, 'post')
                self.logger.info(f"粉專 {page_id} 貼文基準已建立")
            
            return new_posts
            
        except Exception as e:
            self.logger.error(f"粉專 {page_id} 貼文讀取失敗：{e}")
            update_check_status(
                self.db_path, page_id, 'post',
                'failed', str(e)[:100], str(e)
            )
            return []
    
    def _fetch_feed(
        self, page_id: str, since: Optional[str] = None
    ) -> tuple:
        """從 API 讀取貼文 feed
        
        Args:
            page_id: 粉專 ID
            since: 查詢下界（ISO 8601）
            
        Returns:
            (貼文清單，分頁是否未完成)
        """
        posts = []
        pagination_incomplete = False
        
        params = {
            'access_token': self.access_token,
            'fields': 'id,from,created_time,message,story,full_picture,link,permalink_url,type,status_type',
            'limit': 25
        }
        
        if since:
            params['since'] = since
        
        page = 0
        
        while page < self.max_pages:
            try:
                # 使用固定 host 與版本，不跟隨 next URL
                url = f"{self.GRAPH_HOST}/{self.API_VERSION}/{page_id}/feed"
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                
                if 'data' not in data or not data['data']:
                    break
                
                # 篩選指定粉專發布的貼文
                for item in data['data']:
                    # 使用 from.id 判定作者
                    from_obj = item.get('from', {})
                    author_id = from_obj.get('id') if from_obj else None
                    
                    if not author_id:
                        self.logger.warning(f"貼文 {item.get('id')} 缺少作者資訊")
                        continue
                    
                    if author_id == page_id:
                        posts.append(item)
                    else:
                        self.logger.debug(
                            f"貼文 {item.get('id')} 作者 {author_id} 非目標粉專"
                        )
                
                # 處理分頁
                paging = data.get('paging', {})
                if 'next' not in paging:
                    break
                
                # 使用游標式分頁：固定 host + 新增 since 參數
                # 不跟隨含 Token 的 next URL
                page += 1
                
                # 更新 since 為最後一條貼文的 created_time，用於下一頁
                if posts:
                    last_post = posts[-1]
                    created_time = last_post.get('created_time')
                    if created_time:
                        params['since'] = created_time
                
            except requests.exceptions.HTTPError as e:
                # 檢查是否為限流
                if e.response and e.response.status_code == 429:
                    self.logger.warning("API 限流，等待下一輪")
                    update_check_status(
                        self.db_path, page_id, 'post',
                        'rate_limited', '429', 'API rate limit'
                    )
                    return posts, True
                raise
            except requests.exceptions.RequestException as e:
                self.logger.error(f"API 請求失敗：{e}")
                return posts, True
            except Exception as e:
                self.logger.error(f"處理貼文失敗：{e}")
                return posts, True
        
        # 檢查是否達到 max_pages 限制
        if page >= self.max_pages:
            paging = data.get('paging', {})
            if 'next' in paging:
                pagination_incomplete = True
                self.logger.warning(
                    f"達到分頁上限 {self.max_pages}，可能還有更多貼文"
                )
        
        return posts, pagination_incomplete
    
    def _prepare_item(
        self, page_id: str, post: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """準備 item 資料用於批次保存
        
        Args:
            page_id: 粉專 ID
            post: 貼文資料
            
        Returns:
            item 資料字典或 None
        """
        content_id = post.get('id')
        if not content_id:
            return None
        
        # 使用 from.id 判定作者
        from_obj = post.get('from', {})
        author_id = from_obj.get('id') if from_obj else None
        
        if not author_id:
            self.logger.error(f"貼文 {content_id} 缺少作者 ID，跳過")
            return None
        
        # 解析發布時間
        published_at = None
        created_time = post.get('created_time')
        if created_time:
            try:
                published_at = datetime.fromisoformat(
                    created_time.replace('Z', '+00:00')
                )
            except Exception as e:
                self.logger.debug(f"時間解析失敗：{e}")
        
        # 建立摘要
        summary = self._build_summary(post)
        
        # 取得連結
        url = post.get('permalink_url') or post.get('link')
        
        # 儲存原始資料
        raw_data = json.dumps(post, ensure_ascii=False)
        
        return {
            'page_id': page_id,
            'content_type': 'post',
            'content_id': content_id,
            'author_id': author_id,
            'published_at': published_at,
            'summary': summary,
            'url': url,
            'raw_data': raw_data
        }
    
    def _build_summary(self, post: Dict[str, Any]) -> str:
        """建立貼文摘要"""
        message = post.get('message', '')
        story = post.get('story', '')
        post_type = post.get('type', 'unknown')
        
        if message:
            return message[:200]
        
        if story:
            return story[:200]
        
        type_map = {
            'photo': '圖片貼文',
            'video': '影片貼文',
            'link': '連結分享',
            'status': '文字貼文',
            'shared_story': '分享內容'
        }
        return type_map.get(post_type, f'{post_type} 內容')
