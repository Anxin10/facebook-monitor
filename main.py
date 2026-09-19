# Facebook 監控系統 - 主程式入口
# 依 HYBRID_INTEGRATION.md 實作

import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv
import yaml

# 加入 src 目錄到 Python 路徑
sys.path.insert(0, str(Path(__file__).parent / 'src'))

# 載入環境變數
load_dotenv()

def setup_logging():
    """設定日誌系統"""
    log_config = {
        'level': 'INFO',
        'file': 'monitor.log',
        'max_size_mb': 10,
        'backup_count': 3
    }
    
    logging.basicConfig(
        level=getattr(logging, log_config['level']),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_config['file'], encoding='utf-8')
        ]
    )
    return logging.getLogger(__name__)

def load_config(config_path='config.yaml'):
    """載入設定檔"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(f"設定檔未找到：{config_path}")
        return None
    except yaml.YAMLError as e:
        logging.error(f"設定檔格式錯誤：{e}")
        return None

def main():
    """主程式入口"""
    logger = setup_logging()
    logger.info("="*50)
    logger.info("Facebook 監控系統啟動")
    logger.info("="*50)
    
    # 載入設定
    config = load_config()
    if not config:
        logger.error("設定載入失敗，退出")
        sys.exit(1)
    
    logger.info("設定檔載入成功")
    
    # 檢查必要環境變數
    required_env_vars = [
        'FACEBOOK_ACCESS_TOKEN'
    ]
    
    missing_envs = [var for var in required_env_vars if not os.getenv(var)]
    if missing_envs:
        logger.error(f"缺少必要環境變數：{', '.join(missing_envs)}")
        logger.error("請建立 .env 檔案並填寫相關資訊")
        logger.error("可參考 .env.example 範例")
        sys.exit(1)
    
    logger.info("環境變數檢查通過")
    
    # 檢查啟用的監控目標
    enabled_targets = [t for t in config.get('targets', []) if t.get('enabled')]
    if not enabled_targets:
        logger.warning("沒有啟用的監控目標")
        logger.info("請編輯 config.yaml 啟用至少一個目標")
        sys.exit(0)
    
    logger.info(f"啟用 {len(enabled_targets)} 個監控目標")
    
    # 檢查啟用的功能
    posts_enabled = config.get('posts', {}).get('source') == 'graph_api'
    stories_enabled = config.get('stories', {}).get('enabled', False)
    
    logger.info(f"貼文監控：{'啟用' if posts_enabled else '停用'}")
    logger.info(f"限時動態監控：{'啟用' if stories_enabled else '停用（尚未實作）'}")
    
    if stories_enabled:
        logger.warning("限時動態功能尚未實作，stories.enabled 必須維持 false")
    
    # 檢查通知管道設定
    channels = config.get('notifications', {}).get('channels', [])
    if channels:
        logger.info(f"啟用 {len(channels)} 個通知管道")
        for ch in channels:
            logger.info(f"  - {ch.get('id')}: {ch.get('backend')}")
    else:
        logger.info("通知管道未設定")
    
    # 初始化資料庫
    try:
        from database import init_database
        db_path = config.get('storage', {}).get('database', 'monitor.sqlite3')
        init_database(db_path)
        logger.info(f"資料庫初始化完成：{db_path}")
    except ImportError:
        logger.warning("資料庫模組尚未實作，使用暫存模式")
    except Exception as e:
        logger.error(f"資料庫初始化失敗：{e}")
        sys.exit(1)
    
    # 啟動排程器
    try:
        from scheduler import Scheduler
        scheduler = Scheduler(config, logger)
        scheduler.run()
    except ImportError:
        logger.warning("排程器模組尚未實作")
        logger.info("請繼續實作 src/scheduler.py")
    except Exception as e:
        logger.error(f"排程器啟動失敗：{e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
