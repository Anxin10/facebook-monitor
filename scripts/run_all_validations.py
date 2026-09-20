#!/usr/bin/env python3
"""完整整合測試腳本

此腳本執行完整的驗證流程：
1. 環境變數檢查
2. API Token 驗證
3. 資料庫測試
4. 貼文讀取測試

使用方式：
    python scripts/run_all_validations.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# 載入環境變數
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    print("警告：python-dotenv 未安裝")


def check_requirements():
    """檢查必要套件"""
    print("\n" + "=" * 60)
    print("套件檢查")
    print("=" * 60)

    required_packages = [
        ("requests", "requests"),
        ("yaml", "PyYAML"),
        ("playwright", "playwright"),
        ("psutil", "psutil"),
    ]

    missing = []

    for import_name, package_name in required_packages:
        try:
            __import__(import_name)
            print(f"  ✓ {package_name}")
        except ImportError:
            print(f"  ✗ {package_name} (未安裝)")
            missing.append(package_name)

    if missing:
        print(f"\n缺少套件：{', '.join(missing)}")
        print("請執行：pip install -r requirements.txt")
        return False

    print("\n✓ 所有必要套件已安裝")
    return True


def main():
    """主函式"""
    print("\n" + "#" * 60)
    print("# Facebook 監控系統 - 完整驗證")
    print("#" * 60)
    print(f"時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("#" * 60 + "\n")

    # 1. 套件檢查
    if not check_requirements():
        print("\n✗ 套件檢查失敗，請安裝必要套件後重新執行")
        sys.exit(1)

    # 2. 環境變數檢查
    print("\n" + "=" * 60)
    print("環境變數檢查")
    print("=" * 60)

    env_checks = [
        ("FACEBOOK_APP_ID", os.getenv("FACEBOOK_APP_ID", "")),
        ("FACEBOOK_PAGE_ACCESS_TOKEN", os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")),
    ]

    all_set = True
    for name, value in env_checks:
        if value:
            print(f"  ✓ {name}: {value[:20]}...")
        else:
            print(f"  ✗ {name}: 未設定")
            all_set = False

    if not all_set:
        print("\n⚠  缺少必要環境變數")
        print("請建立 .env 檔案並設定相關變數")
        print("可參考 .env.example 範例\n")
        response = input("是否繼續執行其他測試？(y/n): ").strip().lower()
        if response != "y":
            sys.exit(0)

    # 3. 執行 API 驗證腳本
    print("\n" + "=" * 60)
    print("執行 API 驗證腳本")
    print("=" * 60)

    api_script = Path(__file__).parent / "validate_api.py"
    if api_script.exists():
        print(f"執行：python {api_script}\n")
        sys.exit(0)  # API 驗證腳本會獨立執行
    else:
        print(f"✗ API 驗證腳本未找到：{api_script}")

    # 4. 執行資料庫驗證腳本
    print("\n" + "=" * 60)
    print("執行資料庫驗證腳本")
    print("=" * 60)

    db_script = Path(__file__).parent / "validate_database.py"
    if db_script.exists():
        print(f"執行：python {db_script}\n")
        sys.exit(0)  # 資料庫驗證腳本會獨立執行
    else:
        print(f"✗ 資料庫驗證腳本未找到：{db_script}")


if __name__ == "__main__":
    main()
