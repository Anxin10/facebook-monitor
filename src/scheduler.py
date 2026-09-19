"""排程器模組

依 HYBRID_INTEGRATION.md 實作排程功能。
- 使用獨立 Scheduler，保留秒數精度
- 通知顯示時區採設定值而非主機時區
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import schedule


class Scheduler:
    """排程器
    
    依來源分別排程，避免同一目標的檢查重疊。
    """
    
    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """初始化排程器"""
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
            # schedule 支援秒數精度
            self._schedule_every(interval_seconds, self._check_posts, 'posts')
            self.logger.info(f"貼文監控任務已註冊：每 {interval_seconds} 秒")
        
        # 限時動態監控任務（尚未實作）
        stories_config = self.config.get('stories', {})
        if stories_config.get('enabled', False):
            self.logger.warning("限時動態功能尚未實作，stories.enabled 必須維持 false")
        else:
            self.logger.info("限時動態監控未啟用")
        
        # 通知發送任務（每 30 秒）
        self._schedule_every(30, self._send_notifications, 'notifications')
        self.logger.info("通知發送任務已註冊：每 30 秒")
    
    def _schedule_every(
        self, seconds: int, job_func, task_name: str
    ) -> None:
        """依秒數排程任務"""
        if seconds < 60:
            # 小於 1 分鐘，使用 seconds
            schedule.every(seconds).seconds.do(job_func)
        else:
            # 大於等於 1 分鐘，使用 minutes
            minutes = seconds // 60
            schedule.every(minutes).minutes.do(job_func)
    
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
