"""公用工具模組"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional


def format_datetime(dt: Optional[datetime], tz_name: str = 'Asia/Taipei') -> Optional[str]:
    """格式化日期時間
    
    Args:
        dt: 日期時間物件
        tz_name: 目標時區
        
    Returns:
        格式化字串或 None
    """
    if not dt:
        return None
    
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
        dt_local = dt.astimezone(tz)
        return dt_local.strftime('%Y/%m/%d %H:%M:%S')
    except:
        return dt.isoformat()


def truncate_text(text: Optional[str], max_length: int = 100) -> str:
    """截斷文字
    
    Args:
        text: 原文字
        max_length: 最大長度
        
    Returns:
        截斷後文字
    """
    if not text:
        return ''
    
    if len(text) <= max_length:
        return text
    
    return text[:max_length-3] + '...'


def safe_json_dumps(obj: Any, ensure_ascii: bool = False) -> str:
    """安全地將物件轉為 JSON
    
    Args:
        obj: 物件
        ensure_ascii: 是否確保 ASCII
        
    Returns:
        JSON 字串
    """
    try:
        return json.dumps(obj, ensure_ascii=ensure_ascii)
    except:
        return json.dumps(str(obj), ensure_ascii=ensure_ascii)


def retry_with_backoff(
    func,
    max_attempts: int = 5,
    base_delay: float = 30.0,
    backoff_factor: float = 2.0
):
    """重試裝飾器，帶有指數退避
    
    Args:
        func: 要執行的函式
        max_attempts: 最大重試次數
        base_delay: 基礎延遲（秒）
        backoff_factor: 退避係數
    """
    import time
    
    def wrapper(*args, **kwargs):
        last_exception = None
        
        for attempt in range(max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                delay = base_delay * (backoff_factor ** attempt)
                logging.warning(f"嘗試 {attempt + 1}/{max_attempts} 失敗，{delay:.1f}秒後重試：{e}")
                time.sleep(delay)
        
        raise last_exception
    
    return wrapper
