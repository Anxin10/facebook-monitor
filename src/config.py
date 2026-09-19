"""設定載入模組

依設計文件第 7 節實作設定管理。
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


class Config:
    """設定管理類"""

    def __init__(self, config_path: str = "config.yaml"):
        """
        初始化設定

        Args:
            config_path: 設定檔路徑
        """
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        """載入設定檔"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"設定檔未找到：{self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f) or {}

    def reload(self) -> None:
        """重新載入設定"""
        self._load_config()

    @property
    def targets(self) -> List[Dict[str, Any]]:
        """取得監控目標清單"""
        return self._config.get("targets", [])

    @property
    def enabled_targets(self) -> List[Dict[str, Any]]:
        """取得啟用的監控目標"""
        return [t for t in self.targets if t.get("enabled", False)]

    @property
    def posts_config(self) -> Dict[str, Any]:
        """取得貼文監控設定"""
        return self._config.get("posts", {})

    @property
    def stories_config(self) -> Dict[str, Any]:
        """取得限時動態設定"""
        return self._config.get("stories", {})

    @property
    def storage_config(self) -> Dict[str, Any]:
        """取得儲存設定"""
        return self._config.get("storage", {})

    @property
    def notifications_config(self) -> Dict[str, Any]:
        """取得通知設定"""
        return self._config.get("notifications", {})

    @property
    def logging_config(self) -> Dict[str, Any]:
        """取得日誌設定"""
        return self._config.get("logging", {})

    @property
    def runtime_config(self) -> Dict[str, Any]:
        """取得執行環境設定"""
        return self._config.get("runtime", {})

    def get(self, key: str, default: Any = None) -> Any:
        """取得設定值

        Args:
            key: 設定鍵
            default: 預設值

        Returns:
            設定值或預設值
        """
        return self._config.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """支援字典索引語法"""
        return self._config.get(key)

    def __contains__(self, key: str) -> bool:
        """支援 in 運算子"""
        return key in self._config
