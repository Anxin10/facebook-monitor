"""排程器模組 - v0.2

支援秒數精度的獨立排程器。
每個 Scheduler 實例使用獨立的 schedule.Scheduler() 物件。
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import schedule


class Scheduler:
    """獨立排程器

    支援秒數精度，每個實例使用獨立的 Scheduler 物件。
    """

    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """初始化排程器"""
        self.config = config
        self.logger = logger
        self.db_path = config.get("storage", {}).get("database", "monitor.sqlite3")

        # 任務狀態追蹤
        self._running_tasks: Dict[str, bool] = {}
        self._stop_event = False

        # 使用獨立的 Scheduler 實例
        self.scheduler = schedule.Scheduler()

        # 註冊任務
        self._register_tasks()

    def _register_tasks(self) -> None:
        """註冊所有排程任務"""

        # 貼文監控任務
        posts_config = self.config.get("posts", {})
        if posts_config.get("source") == "graph_api":
            interval_seconds = posts_config.get("interval_seconds", 600)
            self._schedule_exact_seconds(interval_seconds, self._check_posts)
            self.logger.info(f"貼文監控任務已註冊：每 {interval_seconds} 秒")

        # 限時動態監控任務（尚未實作）
        stories_config = self.config.get("stories", {})
        if stories_config.get("enabled", False):
            self.logger.warning("限時動態功能尚未實作，stories.enabled 必須維持 false")
        else:
            self.logger.info("限時動態監控未啟用")

        # 通知發送任務（每 30 秒）
        self._schedule_exact_seconds(30, self._send_notifications)
        self.logger.info("通知發送任務已註冊：每 30 秒")

    def _schedule_exact_seconds(self, seconds: int, job_func) -> None:
        """依秒數精確排程任務

        使用獨立 Scheduler 的 seconds 方法，支援秒數精度。
        """
        if seconds > 0:
            self.scheduler.every(seconds).seconds.do(job_func)
            self.logger.debug(f"排程任務：每 {seconds} 秒")

    def _check_posts(self) -> None:
        """執行貼文檢查"""
        self.logger.info("開始執行貼文檢查")

        # 避免重疊執行
        if self._running_tasks.get("posts"):
            self.logger.warning("貼文檢查已在執行中，跳過")
            return

        self._running_tasks["posts"] = True

        try:
            from src.post_fetcher import PostFetcher

            fetcher = PostFetcher(self.config, self.logger)
            fetcher.fetch_all()
        except ImportError:
            self.logger.warning("貼文讀取器模組尚未實作")
        except Exception as e:
            self.logger.error(f"貼文檢查失敗：{e}", exc_info=True)
        finally:
            self._running_tasks["posts"] = False

    def _send_notifications(self) -> None:
        """執行通知發送"""
        try:
            from src.notifier import Notifier

            notifier = Notifier(self.config, self.logger)
            notifier.send_pending()
        except ImportError:
            self.logger.debug("通知發送器模組尚未實作")
        except Exception as e:
            self.logger.error(f"通知發送失敗：{e}", exc_info=True)

    def run(self) -> None:
        """啟動排程器

        阻塞執行，持續監控直到中斷。
        使用 1 秒間隔檢查，確保秒數精度。
        """
        self.logger.info("排程器啟動，等待任務執行...")

        try:
            while not self._stop_event:
                self.scheduler.run_pending()
                time.sleep(1)  # 1 秒間隔，確保秒數精度
        except KeyboardInterrupt:
            self._stop_event = True
            self.logger.info("收到中斷信號，正在停止...")
        except Exception as e:
            self.logger.error(f"排程器異常：{e}", exc_info=True)
            raise
        finally:
            self.logger.info("排程器已停止")

    def stop(self) -> None:
        """停止排程器"""
        self._stop_event = True
        self.logger.info("收到停止信號")
