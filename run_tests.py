#!/usr/bin/env python3
"""測試運行腳本

執行所有離線測試並顯示結果。
"""

import sys
import unittest
from pathlib import Path

# 加入根目錄到路徑
sys.path.insert(0, str(Path(__file__).parent))

def run_tests(verbosity=1):
    """執行測試
    
    Args:
        verbosity: 詳細程度 (0=靜默，1=標準，2=詳細)
    
    Returns:
        測試結果物件
    """
    # 發現測試
    loader = unittest.TestLoader()
    suite = loader.discover('tests', pattern='test_*.py')
    
    # 建立測試運行器
    runner = unittest.TextTestRunner(verbosity=verbosity)
    
    # 執行測試
    result = runner.run(suite)
    
    return result

def main():
    """主函數"""
    print("="*60)
    print("Facebook 監控系統 - 離線測試")
    print("="*60)
    print()
    
    # 執行測試
    result = run_tests(verbosity=2)
    
    print()
    print("="*60)
    print("測試摘要")
    print("="*60)
    print(f"測試數量：{result.testsRun}")
    print(f"失敗：{len(result.failures)}")
    print(f"錯誤：{len(result.errors)}")
    print(f"跳過：{len(result.skipped)}")
    print()
    
    if result.wasSuccessful():
        print("✅ 所有測試通過！")
        return 0
    else:
        print("❌ 有測試失敗")
        
        if result.failures:
            print("\n失敗詳情:")
            for test, traceback in result.failures:
                print(f"  - {test}")
        
        if result.errors:
            print("\n錯誤詳情:")
            for test, traceback in result.errors:
                print(f"  - {test}")
        
        return 1

if __name__ == '__main__':
    sys.exit(main())
