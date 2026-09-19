"""貼文讀取器模組 - Core Correctness 版本

v0.2 核心修正：
- 使用 /{page_id}/posts 端點（非 /feed），直接取得粉專發布的貼文
- 真實 cursor pagination（paging.cursors.after）
- 可配置 API version（預設 v26.0）
- incomplete fetch = no commit
- 首次基準不 spam（notify_existing_on_first_run）
- 統一的 Page token 處理
"""

import os
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
import requests

from src.database import (
    update_check_status, set_baseline_ready,
    get_check_status, save_batch_with_transaction
)


class GraphClient:
    """Facebook Graph API 客戶端
    
    統一的 API 訪問層，支援：
    - 可配置的 API version
    - 統一的 token 處理
    - 真實 cursor pagination
    - 錯誤處理與限流辨識
    """
    
    GRAPH_HOST = 'https://graph.facebook.com'
    DEFAULT_VERSION = 'v26.0'  # 使用最新穩定版
    
    def __init__(
        self,
        access_token: str,
        api_version: Optional[str] = None,
        logger: Optional[logging.Logger] = None
    ):
        """初始化 Graph API 客戶端
        
        Args:
            access_token: Facebook Access Token
            api_version: API version（預設 v26.0）
            logger: 日誌記錄器
        """
        self.access_token = access_token
        self.api_version = api_version or self.DEFAULT_VERSION
        self.logger = logger or logging.getLogger(__name__)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'facebook-monitor/0.2'
        })
    
    def _build_url(self, path: str) -> str:
        """建立完整的 API URL"""
        return f"{self.GRAPH_HOST}/{self.api_version}/{path}"
    
    def _build_params(self, extra_params: Optional[Dict] = None) -> Dict:
        """建立請求參數"""
        params = {'access_token': self.access_token}
        if extra_params:
            params.update(extra_params)
        return params
    
    def get(self, path: str, params: Optional[Dict] = None, timeout: int = 30) -> requests.Response:
        """發送 GET 請求
        
        Args:
            path: API 路徑（不含 version）
            params: 查詢參數
            timeout: 超時秒數
            
        Returns:
            Response 物件
            
        Raises:
            requests.HTTPError: HTTP 錯誤（含 429 限流）
            requests.RequestException: 其他請求錯誤
        """
        url = self._build_url(path)
        request_params = self._build_params(params)
        
        response = self.session.get(url, params=request_params, timeout=timeout)
        response.raise_for_status()
        return response
    
    def is_rate_limited(self, exception: requests.HTTPError) -> bool:
        """檢查是否為 API 限流"""
        return (hasattr(exception, 'response') and 
                exception.response is not None and
                exception.response.status_code == 429)
    
    def get_retry_after(self, exception: requests.HTTPError) -> Optional[int]:
        """取得 Retry-After 秒數"""
        if hasattr(exception, 'response') and exception.response:
            return exception.response.headers.get('Retry-After')
        return None


class PostFetcher:
    """貼文讀取器
    
    v0.2 核心修正版本：
    - 使用 /{page_id}/posts 端點
    - 真實 cursor pagination
    - incomplete fetch = no commit
    - 首次基準不 spam
    """
    
    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """初始化貼文讀取器
        
        Args:
            config: 設定字典
            logger: 日誌記錄器
        """
        self.config = config
        self.logger = logger
        self.db_path = config.get('storage', {}).get('database', 'monitor.sqlite3')
        
        # API 設定
        self.access_token = os.getenv('FACEBOOK_ACCESS_TOKEN')
        if not self.access_token:
            self.logger.error("缺少 FACEBOOK_ACCESS_TOKEN")
        
        # 貼文監控設定
        self.posts_config = config.get('posts', {})
        self.max_pages = self.posts_config.get('max_pages', 5)
        self.initial_lookback_days = self.posts_config.get('initial_lookback_days', 7)
        self.api_version = self.posts_config.get('api_version', GraphClient.DEFAULT_VERSION)
        
        # 通知設定
        self.notifications_config = config.get('notifications', {})
        self.notify_existing_on_first_run = self.notifications_config.get(
            'notify_existing_on_first_run', False
        )
        
        # 建立 Graph API 客戶端
        self.graph = GraphClient(
            access_token=self.access_token,
            api_version=self.api_version,
            logger=self.logger
        )
    
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
            now = datetime.now(timezone.utc)
            if baseline_ready and last_success_at:
                try:
                    last_success = datetime.fromisoformat(
                        last_success_at.replace('Z', '+00:00')
                    )
                    since_time = last_success - timedelta(hours=1)
                except Exception as e:
                    self.logger.warning(f"時間解析失敗：{e}，使用預設 lookback")
                    since_time = now - timedelta(days=self.initial_lookback_days)
            else:
                since_time = now - timedelta(days=self.initial_lookback_days)
            
            since_param = since_time.isoformat()
            self.logger.debug(f"查詢下界：{since_param}")
            
            # 讀取貼文（使用 /posts 端點）
            posts, pagination_incomplete, error = self._fetch_posts(
                page_id, since_param
            )
            
            # 若有錯誤，不保存部分資料
            if error:
                self.logger.error(f"貼文讀取錯誤：{error}")
                update_check_status(
                    self.db_path, page_id, 'post',
                    'failed', error.get('code'), error.get('message'),
                    pagination_incomplete=False
                )
                return []
            
            if not posts:
                # 空列表視為成功（無新貼文）
                self.logger.info(f"粉專 {page_id} 無新貼文")
                
                # 首次成功後標記基準已建立
                if not baseline_ready:
                    set_baseline_ready(self.db_path, page_id, 'post')
                    self.logger.info(f"粉專 {page_id} 貼文基準已建立")
                
                update_check_status(
                    self.db_path, page_id, 'post',
                    'success', None, None, pagination_incomplete=False
                )
                return []
            
            # 處理新貼文（先收集，不立即保存）
            new_posts = []
            existing_count = 0
            
            for post in posts:
                content_id = post.get('id')
                if not content_id:
                    continue
                
                # 檢查是否已存在（使用資料庫查詢）
                if self._item_exists(page_id, 'post', content_id):
                    existing_count += 1
                    continue
                
                new_posts.append(post)
                
                # 首次基準時，根據設定决定是否通知
                if baseline_ready or self.notify_existing_on_first_run:
                    self.logger.info(f"發現新貼文：{content_id}")
                else:
                    self.logger.debug(f"基準期間貼文：{content_id}（不通知）")
            
            self.logger.info(
                f"共 {len(posts)} 則貼文，新 {len(new_posts)} 則，既有 {existing_count} 則"
            )
            
            # 若有新貼文，批次保存
            if new_posts:
                success = self._save_new_posts(
                    page_id, new_posts, baseline_ready, pagination_incomplete
                )
                
                if not success:
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
            self.logger.error(f"粉專 {page_id} 貼文讀取失敗：{e}", exc_info=True)
            update_check_status(
                self.db_path, page_id, 'post',
                'failed', 'exception', str(e)[:200]
            )
            return []
    
    def _fetch_posts(
        self, page_id: str, since: Optional[str] = None
    ) -> Tuple[List[Dict], bool, Optional[Dict]]:
        """從 API 讀取粉專貼文
        
        使用 /{page_id}/posts 端點，直接取得粉專發布的貼文。
        使用真實 cursor pagination（paging.cursors.after）。
        
        Args:
            page_id: 粉專 ID
            since: 查詢下界（ISO 8601）
            
        Returns:
            (貼文清單，分頁是否未完成，錯誤資訊)
        """
        posts = []
        pagination_incomplete = False
        
        params = {
            'fields': 'id,created_time,message,story,full_picture,link,permalink_url,type,status_type',
            'limit': 25
        }
        
        if since:
            params['since'] = since
        
        after_cursor = None
        page_count = 0
        
        try:
            while page_count < self.max_pages:
                # 加入 cursor
                if after_cursor:
                    params['after'] = after_cursor
                
                # 呼叫 /posts 端點
                path = f"{page_id}/posts"
                response = self.graph.get(path, params)
                data = response.json()
                
                if 'data' not in data or not data['data']:
                    break
                
                # 加入貼文（/posts 端點已保證是粉專發布）
                posts.extend(data['data'])
                
                # 處理分頁
                paging = data.get('paging', {})
                cursors = paging.get('cursors', {})
                
                if not paging.get('next'):
                    break
                
                # 使用 cursors.after 作為下一頁的游標
                after_cursor = cursors.get('after')
                if not after_cursor:
                    # 沒有 cursors，表示分頁結束
                    break
                
                page_count += 1
                self.logger.debug(f"分頁 {page_count}，取得 {len(data['data'])} 則貼文")
            
            # 檢查是否達到 max_pages 限制
            if page_count >= self.max_pages:
                if paging.get('next'):
                    pagination_incomplete = True
                    self.logger.warning(
                        f"達到分頁上限 {self.max_pages}，可能還有更多貼文"
                    )
            
            return posts, pagination_incomplete, None
            
        except requests.HTTPError as e:
            if self.graph.is_rate_limited(e):
                self.logger.warning("API 限流")
                retry_after = self.graph.get_retry_after(e)
                if retry_after:
                    self.logger.warning(f"建議等待 {retry_after} 秒")
                return posts, True, {'code': '429', 'message': 'API rate limit'}
            
            # 其他 HTTP 錯誤
            error_msg = str(e)
            if hasattr(e, 'response') and e.response:
                try:
                    error_data = e.response.json()
                    error_msg = error_data.get('error', {}).get('message', error_msg)
                except:
                    pass
            
            return posts, True, {'code': str(e.response.status_code), 'message': error_msg}
            
        except requests.RequestException as e:
            self.logger.error(f"API 請求失敗：{e}")
            return posts, True, {'code': 'network', 'message': str(e)}
        
        except Exception as e:
            self.logger.error(f"處理貼文失敗：{e}", exc_info=True)
            return posts, True, {'code': 'exception', 'message': str(e)}
    
    def _item_exists(self, page_id: str, content_type: str, content_id: str) -> bool:
        """檢查內容是否已存在"""
        from src.database import item_exists
        return item_exists(self.db_path, page_id, content_type, content_id)
    
    def _save_new_posts(
        self,
        page_id: str,
        new_posts: List[Dict[str, Any]],
        baseline_ready: bool,
        pagination_incomplete: bool
    ) -> bool:
        """批次保存新貼文
        
        Args:
            page_id: 粉專 ID
            new_posts: 新貼文清單
            baseline_ready: 基準是否已建立
            pagination_incomplete: 分頁是否未完成
            
        Returns:
            True 若成功
        """
        items_to_save = []
        notifications_to_add = []
        
        # 取得啟用的通知管道
        enabled_channels = self.notifications_config.get('channels', [])
        
        for post in new_posts:
            content_id = post.get('id')
            
            # 準備 item 資料
            item_data = self._prepare_item(page_id, post)
            if not item_data:
                continue
            
            items_to_save.append(item_data)
            
            # 準備通知（若啟用了通知管道）
            # 首次基準時，根據 notify_existing_on_first_run 決定
            if enabled_channels and (baseline_ready or self.notify_existing_on_first_run):
                for channel in enabled_channels:
                    notifications_to_add.append({
                        'page_id': page_id,
                        'content_type': 'post',
                        'content_id': content_id,
                        'channel_id': channel.get('id'),
                        'backend': channel.get('backend')
                    })
        
        if not items_to_save:
            return True
        
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
                f"保存 {len(items_to_save)} 則新貼文，"
                f"{len(notifications_to_add)} 則通知"
            )
        
        return success
    
    def _prepare_item(
        self, page_id: str, post: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """準備 item 資料用於批次保存"""
        content_id = post.get('id')
        if not content_id:
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
            'author_id': page_id,  # /posts 端點保證是該粉專
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
