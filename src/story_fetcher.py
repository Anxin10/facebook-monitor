"""限時動態讀取器模組

依設計文件第 2.2、3 節，此模組標記為「待驗證」。
官方 API 未明確支援限時動態讀取，需先驗證可行性。
"""

import logging
from typing import Any, Dict, List, Optional

from src.database import (
    add_item, item_exists, update_check_status, set_baseline_ready,
    get_check_status
)


class StoryFetcher:
    """限時動態讀取器
    
    警告：此功能尚未完成驗證，僅供測試用途。
    """
    
    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """
        初始化限時動態讀取器
        
        Args:
            config: 設定字典
            logger: 日誌記錄器
        """
        self.config = config
        self.logger = logger
        self.db_path = config.get('storage', {}).get('database', 'monitor.sqlite3')
        
        self.logger.warning("限時動態讀取器尚未完成驗證")
    
    def fetch_all(self) -> None:
        """對所有啟用目標執行限時動態讀取"""
        self.logger.warning("限時動態功能尚未驗證，跳過檢查")
        
        # 未來實作時，應：
        # 1. 驗證官方 API 是否支援
        # 2. 若否，評估 Playwright 方案
        # 3. 確保能取得每則限動的穩定識別碼
        # 4. 不繞過登入驗證、存取限制或驗證碼
        
        targets = self.config.get('targets', [])
        enabled_targets = [t for t in targets if t.get('enabled', False)]
        
        for target in enabled_targets:
            page_id = target.get('page_id')
            if page_id:
                update_check_status(
                    self.db_path, page_id, 'story',
                    'failed', 'not_implemented', '限時動態功能尚未驗證'
                )
    
    def fetch_page_stories(self, page_id: str) -> List[Dict[str, Any]]:
        """讀取單一粉專的限時動態
        
        Args:
            page_id: 粉專 ID
            
        Returns:
            空清單（待實作）
        """
        self.logger.warning(f"限時動態讀取未實作：{page_id}")
        return []
