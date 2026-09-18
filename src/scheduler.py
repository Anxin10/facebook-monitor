"""排程器模組

依設計文件第 3、4 節實作排程功能。
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Callable, Optional
import schedule

from src.database import (
    get_check_status, update_check_status, set_baseline_ready
)


class Scheduler:
    """排程器
    
    依來源分別排程，避免同一目標的檢查重疊。
    """
    
    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """
        初始化排程器
        
        Args:
            config: 設定字典
            logger: 日誌記錄器
        """
        self.config = config
        self.logger = logger
        self.db_path = config.get('storage', {}).get('database', 'monitor.sqlite3')
        
        # 任務狀態追蹤
        self._running_tasks: Dict[str, bool] = {}
        
        # 註冊任務
        self._register_tasks()
    
    def _register_tasks(self) -> None:
        """註冊所有排程任務"""
        
        # 貼文監控任務
        posts_config = self.config.get('posts', {})
        if posts_config.get('source') == 'graph_api':
            interval_seconds = posts_config.get('interval_seconds', 600)
            interval_minutes = interval_seconds // 60
            
            schedule.every(interval_minutes).minutes.do(self._check_posts)
            self.logger.info(f"貼文監控任務已註冊：每 {interval_minutes} 分鐘")
        
        # 限時動態監控任務（待驗證後啟用）
        stories_config = self.config.get('stories', {})
        if stories_config.get('enabled', False):
            interval_seconds = stories_config.get('interval_seconds', 300)
            interval_minutes = interval_seconds // 60
            
            schedule.every(interval_minutes).minutes.do(self._check_stories)
            self.logger.info(f"限時動態監控任務已註冊：每 {interval_minutes} 分鐘")
        else:
            self.logger.info("限時動態監控未啟用")
        
        # 通知發送任務
        schedule.every(1).minutes.do(self._send_notifications)
        self.logger.info("通知發送任務已註冊：每 1 分鐘")
    
    def _check_posts(self) -> None:
        """執行貼文檢查"""
        self.logger.info("開始執行貼文檢查")
        
        # 避免重疊執行
        if self._running_tasks.get('posts'):
            self.logger.warning("貼文檢查已在執行中，跳過")
            return
        
        self._running_tasks['posts'] = True
        
        try:
            from src.post_fetcher import PostFetcher
            fetcher = PostFetcher(self.config, self.logger)
            fetcher.fetch_all()
        except ImportError:
            self.logger.warning("貼文讀取器模組尚未實作")
        except Exception as e:
            self.logger.error(f"貼文檢查失敗：{e}")
        finally:
            self._running_tasks['posts'] = False
    
    def _check_stories(self) -> None:
        """執行限時動態檢查"""
        self.logger.info("開始執行限時動態檢查")
        
        if self._running_tasks.get('stories'):
            self.logger.warning("限時動態檢查已在執行中，跳過")
            return
        
        self._running_tasks['stories'] = True
        
        try:
            from src.story_fetcher import StoryFetcher
            fetcher = StoryFetcher(self.config, self.logger)
            fetcher.fetch_all()
        except ImportError:
            self.logger.warning("限時動態讀取器模組尚未實作（待驗證）")
        except Exception as e:
            self.logger.error(f"限時動態檢查失敗：{e}")
        finally:
            self._running_tasks['stories'] = False
    
    def _send_notifications(self) -> None:
        """執行通知發送"""
        try:
            from src.notifier import Notifier
            notifier = Notifier(self.config, self.logger)
            notifier.send_pending()
        except ImportError:
            self.logger.debug("通知發送器模組尚未實作")
        except Exception as e:
            self.logger.error(f"通知發送失敗：{e}")
    
    def run(self) -> None:
        """啟動排程器
        
        阻塞執行，持續監控直到中斷。
        """
        self.logger.info("排程器啟動，等待任務執行...")
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("收到中斷信號，正在停止...")
        except Exception as e:
            self.logger.error(f"排程器異常：{e}")
            raise
