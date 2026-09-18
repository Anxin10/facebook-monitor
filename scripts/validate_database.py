#!/usr/bin/env python3
"""SQLite 資料庫驗證腳本

此腳本用於測試資料庫模組功能是否正常。

使用方式：
    python scripts/validate_database.py
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

# 加入 src 目錄到路徑
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from src.database import (
        init_database,
        add_or_update_target,
        get_enabled_targets,
        add_item,
        item_exists,
        get_items_by_page,
        update_check_status,
        get_check_status,
        set_baseline_ready,
        add_notification,
        get_pending_notifications,
        update_notification_status
    )
except ImportError as e:
    print(f"錯誤：無法匯入 database 模組：{e}")
    print("請確認 src/database.py 存在且正確")
    sys.exit(1)


class DatabaseValidator:
    """資料庫驗證器"""
    
    def __init__(self, db_path: str = 'test_monitor.sqlite3'):
        self.db_path = db_path
        self.test_page_id = '100054441671873'
    
    def log(self, message: str, level: str = 'INFO'):
        """記錄訊息"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [{level}] {message}")
    
    def test_init(self):
        """測試資料庫初始化"""
        print("\n" + "="*60)
        print("1. 資料庫初始化")
        print("="*60)
        
        try:
            init_database(self.db_path)
            self.log(f"資料庫初始化成功：{self.db_path}", "INFO")
            return True
        except Exception as e:
            self.log(f"資料庫初始化失敗：{e}", "ERROR")
            return False
    
    def test_target_operations(self):
        """測試目標 CRUD 操作"""
        print("\n" + "="*60)
        print("2. 目標操作測試")
        print("="*60)
        
        try:
            # 新增目標
            add_or_update_target(
                self.db_path,
                page_id=self.test_page_id,
                url='https://www.facebook.com/profile.php?id=100054441671873',
                account_type='page_assumed',
                enabled=True
            )
            self.log("目標新增成功", "INFO")
            
            # 取得目標
            targets = get_enabled_targets(self.db_path)
            self.log(f"取得啟用目標：{len(targets)} 個", "INFO")
            
            if targets:
                target = targets[0]
                self.log(f"  page_id: {target['page_id']}", "INFO")
                self.log(f"  url: {target['url']}", "INFO")
                self.log(f"  enabled: {target['enabled']}", "INFO")
            
            return True
        except Exception as e:
            self.log(f"目標操作失敗：{e}", "ERROR")
            return False
    
    def test_item_operations(self):
        """測試內容項目操作"""
        print("\n" + "="*60)
        print("3. 內容項目操作測試")
        print("="*60)
        
        try:
            # 測試存在性檢查
            exists = item_exists(self.db_path, self.test_page_id, 'post', 'test_post_1')
            self.log(f"測試貼文是否存在（預期 False）: {exists}", "INFO")
            
            # 新增貼文
            published_at = datetime.now(timezone.utc)
            result = add_item(
                self.db_path,
                page_id=self.test_page_id,
                content_type='post',
                content_id='test_post_1',
                author_id=self.test_page_id,
                published_at=published_at,
                summary='測試貼文摘要',
                url='https://www.facebook.com/posts/test_post_1',
                raw_data='{"test": "data"}'
            )
            
            if result:
                self.log("貼文新增成功", "INFO")
            else:
                self.log("貼文已存在或新增失敗", "WARNING")
            
            # 再次新增同一貼文（應失敗）
            result2 = add_item(
                self.db_path,
                page_id=self.test_page_id,
                content_type='post',
                content_id='test_post_1',
                author_id=self.test_page_id,
                published_at=published_at,
                summary='測試貼文摘要',
                url='https://www.facebook.com/posts/test_post_1',
                raw_data='{"test": "data"}'
            )
            
            if not result2:
                self.log("重複貼文正確被拒絕（冪等性通過）", "INFO")
            else:
                self.log("重複貼文未被拒絕（冪等性失敗）", "ERROR")
            
            # 檢查存在性
            exists = item_exists(self.db_path, self.test_page_id, 'post', 'test_post_1')
            self.log(f"測試貼文是否存在（預期 True）: {exists}", "INFO")
            
            # 取得貼文清單
            items = get_items_by_page(self.db_path, self.test_page_id, 'post')
            self.log(f"取得貼文清單：{len(items)} 則", "INFO")
            
            return True
        except Exception as e:
            self.log(f"內容項目操作失敗：{e}", "ERROR")
            import traceback
            traceback.print_exc()
            return False
    
    def test_check_operations(self):
        """測試檢查狀態操作"""
        print("\n" + "="*60)
        print("4. 檢查狀態操作測試")
        print("="*60)
        
        try:
            # 更新檢查狀態
            update_check_status(
                self.db_path,
                self.test_page_id,
                'post',
                'success',
                None,
                None
            )
            self.log("檢查狀態更新成功（success）", "INFO")
            
            # 取得檢查狀態
            status = get_check_status(self.db_path, self.test_page_id, 'post')
            if status:
                self.log(f"檢查狀態：{status['status']}", "INFO")
                self.log(f"上次成功時間：{status['last_success_at']}", "INFO")
            
            # 標記基準已建立
            set_baseline_ready(self.db_path, self.test_page_id, 'post')
            status = get_check_status(self.db_path, self.test_page_id, 'post')
            if status and status.get('baseline_ready'):
                self.log("基準已建立標記成功", "INFO")
            
            # 測試失敗狀態
            update_check_status(
                self.db_path,
                self.test_page_id,
                'post',
                'failed',
                'AUTH_ERROR',
                'Token 過期'
            )
            status = get_check_status(self.db_path, self.test_page_id, 'post')
            if status and status.get('status') == 'failed':
                self.log("失敗狀態記錄成功", "INFO")
                self.log(f"  錯誤代碼：{status['error_code']}", "INFO")
                self.log(f"  錯誤訊息：{status['error_message']}", "INFO")
            
            return True
        except Exception as e:
            self.log(f"檢查狀態操作失敗：{e}", "ERROR")
            return False
    
    def test_notification_operations(self):
        """測試通知操作"""
        print("\n" + "="*60)
        print("5. 通知操作測試")
        print("="*60)
        
        try:
            # 新增通知
            result = add_notification(
                self.db_path,
                self.test_page_id,
                'post',
                'test_post_1',
                'line'
            )
            
            if result:
                self.log("通知新增成功", "INFO")
            else:
                self.log("通知已存在", "INFO")
            
            # 再次新增同一通知（應失敗）
            result2 = add_notification(
                self.db_path,
                self.test_page_id,
                'post',
                'test_post_1',
                'line'
            )
            
            if not result2:
                self.log("重複通知正確被拒絕（冪等性通過）", "INFO")
            
            # 取得待發送通知
            pending = get_pending_notifications(self.db_path, channel='line')
            self.log(f"待發送通知：{len(pending)} 則", "INFO")
            
            if pending:
                notification = pending[0]
                self.log(f"  內容 ID: {notification['content_id']}", "INFO")
                self.log(f"  狀態：{notification['status']}", "INFO")
                self.log(f"  管道：{notification['channel']}", "INFO")
            
            # 更新通知狀態為已發送
            if pending:
                update_notification_status(
                    self.db_path,
                    pending[0]['id'],
                    'sent'
                )
                self.log("通知狀態更新為 'sent'", "INFO")
            
            # 測試失敗重試
            update_notification_status(
                self.db_path,
                pending[0]['id'],
                'failed',
                '網路錯誤'
            )
            self.log("通知狀態更新為 'failed'（將安排重試）", "INFO")
            
            return True
        except Exception as e:
            self.log(f"通知操作失敗：{e}", "ERROR")
            return False
    
    def run_all_tests(self):
        """執行所有測試"""
        print("\n" + "#"*60)
        print("# SQLite 資料庫驗證腳本")
        print("#"*60)
        print(f"測試資料庫：{self.db_path}")
        print("#"*60 + "\n")
        
        results = []
        
        # 執行測試
        results.append(('資料庫初始化', self.test_init()))
        results.append(('目標操作', self.test_target_operations()))
        results.append(('內容項目操作', self.test_item_operations()))
        results.append(('檢查狀態操作', self.test_check_operations()))
        results.append(('通知操作', self.test_notification_operations()))
        
        # 總結
        print("\n" + "="*60)
        print("測試總結")
        print("="*60)
        
        passed = sum(1 for _, result in results if result)
        failed = sum(1 for _, result in results if not result)
        
        for name, result in results:
            status = '✓ PASS' if result else '✗ FAIL'
            print(f"  {status}: {name}")
        
        print(f"\n通過：{passed}")
        print(f"失敗：{failed}")
        
        if failed > 0:
            print("\n⚠  部分測試失敗，請檢查資料庫模組")
        else:
            print("\n✓ 所有測試通過！資料庫模組運作正常。")
        
        # 清理測試資料庫
        response = input("\n是否刪除測試資料庫？(y/n): ").strip().lower()
        if response == 'y':
            try:
                Path(self.db_path).unlink()
                print(f"測試資料庫已刪除：{self.db_path}")
            except Exception as e:
                print(f"刪除失敗：{e}")
        
        return failed == 0


def main():
    """主函式"""
    validator = DatabaseValidator()
    success = validator.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
