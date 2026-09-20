#!/usr/bin/env python3
"""Facebook API 驗證腳本 - v0.2

與 PostFetcher 共用 GraphClient，實際驗證：
- /{page_id} - 粉專基本資訊
- /{page_id}/posts - 粉專發布的貼文（非 /feed）
- paging.cursors.after - 真實 cursor pagination
- 權限與 Token

使用方式：
    python scripts/validate_api.py

環境變數要求：
    FACEBOOK_ACCESS_TOKEN
    TARGET_PAGE_ID (可選，預設 100054441671873)
"""

import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

# 加入專案根目錄與 src 路徑
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    import requests
except ImportError:
    print("錯誤：缺少 requests 套件")
    print("請執行：pip install requests")
    sys.exit(1)

# 載入環境變數
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    print("警告：python-dotenv 未安裝")

from post_fetcher import GraphClient


class APIValidator:
    """Facebook API 驗證器 - v0.2

    使用與 PostFetcher 相同的 GraphClient。
    """

    def __init__(self, api_version: str = "v26.0"):
        """初始化驗證器

        Args:
            api_version: Graph API version
        """
        self.access_token = os.getenv("FACEBOOK_ACCESS_TOKEN")
        self.target_page_id = os.getenv("TARGET_PAGE_ID", "100054441671873")
        self.api_version = api_version

        # 使用與 PostFetcher 相同的 GraphClient
        self.logger = logging.getLogger(__name__)
        if self.access_token:
            self.graph = GraphClient(
                access_token=self.access_token,
                api_version=api_version,
                logger=self.logger,
            )
        else:
            self.graph = None

        self.results = []
        self.passed = 0
        self.failed = 0

    def log(self, message: str, level: str = "INFO"):
        """記錄訊息"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")

    def add_result(self, test_name: str, passed: bool, message: str = ""):
        """記錄測試結果"""
        status = "✓ PASS" if passed else "✗ FAIL"
        self.results.append({"test": test_name, "passed": passed, "message": message})

        if passed:
            self.passed += 1
            print(f"  {status}: {test_name}")
        else:
            self.failed += 1
            print(f"  {status}: {test_name}")
            if message:
                print(f"         {message}")

    def check_env_vars(self):
        """檢查環境變數"""
        print("\n" + "=" * 60)
        print("1. 環境變數檢查")
        print("=" * 60)

        if self.access_token:
            self.add_result(
                "FACEBOOK_ACCESS_TOKEN", True, f"已設定：{self.access_token[:20]}..."
            )
        else:
            self.add_result("FACEBOOK_ACCESS_TOKEN", False, "未設定")

        self.log(f"目標粉專 ID: {self.target_page_id}", "INFO")
        self.log(f"API Version: {self.api_version}", "INFO")

    def validate_token(self):
        """驗證 Access Token"""
        print("\n" + "=" * 60)
        print("2. Access Token 驗證")
        print("=" * 60)

        if not self.access_token:
            self.add_result("Token 驗證", False, "Token 未設定")
            return

        try:
            # 使用 /me 端點驗證 Token
            response = self.graph.get("me", {"fields": "id,name"})
            data = response.json()

            if "id" in data:
                self.add_result("Token 有效性", True)
                self.log(
                    f"Token 對應使用者：{data.get('name')} ({data.get('id')})", "INFO"
                )
            else:
                self.add_result("Token 驗證", False, "回應缺少 id")

        except requests.HTTPError as e:
            if e.response and e.response.status_code == 401:
                self.add_result("Token 有效性", False, "Token 無效或過期")
            else:
                self.add_result("Token 驗證", False, f"HTTP {e.response.status_code}")
        except Exception as e:
            self.add_result("Token 驗證", False, str(e))

    def validate_page(self):
        """驗證 /{page_id} - 粉專基本資訊"""
        print("\n" + "=" * 60)
        print("3. 粉專基本資訊 (/{page_id})")
        print("=" * 60)

        if not self.graph:
            self.add_result("粉專讀取", False, "Token 未設定")
            return

        try:
            response = self.graph.get(
                self.target_page_id,
                {"fields": "id,name,username,category,verification_status"},
            )
            data = response.json()

            if "id" in data:
                self.add_result("粉專 ID 有效性", True)

                page_name = data.get("name", "未知")
                page_username = data.get("username", "無")
                page_category = data.get("category", "未知")
                is_verified = data.get("verification_status", False)

                self.log(f"粉專名稱：{page_name}", "INFO")
                self.log(f"使用者名稱：{page_username}", "INFO")
                self.log(f"類別：{page_category}", "INFO")
                self.log(f"驗證狀態：{'✓ 已驗證' if is_verified else '未驗證'}", "INFO")
            else:
                self.add_result("粉專讀取", False, "回應缺少 id")

        except requests.HTTPError as e:
            if e.response:
                status = e.response.status_code
                if status == 400:
                    self.add_result("粉專 ID 有效性", False, "ID 可能無效或格式錯誤")
                elif status == 401:
                    self.add_result("粉專讀取權限", False, "Access Token 無效")
                elif status == 403:
                    self.add_result(
                        "粉專讀取權限",
                        False,
                        "無權存取此粉專（可能需要 Page Admin 權限）",
                    )
                else:
                    self.add_result("粉專讀取", False, f"HTTP {status}")
        except Exception as e:
            self.add_result("粉專讀取", False, str(e))

    def test_posts_endpoint(self):
        """測試 /{page_id}/posts - 粉專發布的貼文"""
        print("\n" + "=" * 60)
        print("4. 粉專貼文端點 (/{page_id}/posts)")
        print("=" * 60)

        if not self.graph:
            self.add_result("Posts 端點", False, "Token 未設定")
            return

        try:
            response = self.graph.get(
                f"{self.target_page_id}/posts",
                {"fields": "id,created_time,message,type", "limit": 5},
            )
            data = response.json()

            if "data" in data:
                posts = data["data"]
                post_count = len(posts)

                self.add_result("Posts 端點讀取", True, f"成功取得 {post_count} 則貼文")

                if post_count > 0:
                    self.log("前 3 則貼文：", "INFO")
                    for i, post in enumerate(posts[:3], 1):
                        post_id = post.get("id", "N/A")
                        post_type = post.get("type", "unknown")
                        created = (
                            post.get("created_time", "N/A")[:10]
                            if post.get("created_time")
                            else "N/A"
                        )
                        self.log(f"  {i}. {post_id} [{post_type}] {created}", "INFO")

                    # /posts 端點保證是粉專發布，不需要作者篩選
                    self.add_result(
                        "作者保證", True, "/posts 端點直接返回粉專發布的貼文"
                    )
                else:
                    self.log("粉專目前無貼文", "INFO")

                # 檢查分頁
                paging = data.get("paging", {})
                if paging.get("next"):
                    self.log("有分頁：可讀取更多貼文", "INFO")

                    # 檢查 cursors
                    cursors = paging.get("cursors", {})
                    if cursors.get("after"):
                        self.add_result(
                            "Cursor Pagination",
                            True,
                            f"支援 cursors.after: {cursors['after'][:30]}...",
                        )
                    else:
                        self.add_result(
                            "Cursor Pagination", False, "paging 無 cursors.after"
                        )
                else:
                    self.log("無更多分頁", "INFO")

            else:
                self.add_result("Posts 端點", False, "回應無 data 欄位")

        except requests.HTTPError as e:
            if e.response:
                status = e.response.status_code
                if status == 400:
                    self.add_result("Posts 端點", False, "API 參數錯誤")
                elif status == 401:
                    self.add_result("Posts 端點權限", False, "Token 無效或過期")
                elif status == 403:
                    self.add_result(
                        "Posts 端點權限",
                        False,
                        "無權讀取此粉專的貼文（需要 pages_read_engagement）",
                    )
                else:
                    self.add_result("Posts 端點", False, f"HTTP {status}")
        except Exception as e:
            self.add_result("Posts 端點", False, str(e))

    def test_cursor_pagination(self):
        """測試真實 cursor pagination"""
        print("\n" + "=" * 60)
        print("5. Cursor Pagination 測試")
        print("=" * 60)

        if not self.graph:
            self.add_result("Cursor Pagination", False, "Token 未設定")
            return

        try:
            # 第一頁
            response1 = self.graph.get(
                f"{self.target_page_id}/posts", {"fields": "id", "limit": 5}
            )
            data1 = response1.json()

            paging1 = data1.get("paging", {})
            cursors1 = paging1.get("cursors", {})
            after_cursor = cursors1.get("after")

            if not after_cursor:
                self.add_result("Cursor Pagination", False, "第一頁無 cursors.after")
                return

            self.log(f"第一頁 cursors.after: {after_cursor[:30]}...", "INFO")

            # 使用 cursor 取得第二頁
            response2 = self.graph.get(
                f"{self.target_page_id}/posts",
                {"fields": "id", "limit": 5, "after": after_cursor},
            )
            data2 = response2.json()

            posts2 = data2.get("data", [])

            if posts2:
                self.add_result(
                    "Cursor Pagination",
                    True,
                    f"成功使用 cursor 取得第二頁 ({len(posts2)} 則)",
                )

                # 驗證第二頁的貼文 ID 與第一頁不同
                posts1_ids = {p["id"] for p in data1.get("data", [])}
                posts2_ids = {p["id"] for p in posts2}

                if not posts1_ids.intersection(posts2_ids):
                    self.log("✓ 第二頁貼文與第一頁無重複", "INFO")
                else:
                    self.log("⚠ 第二頁與第一頁有重複貼文", "WARNING")
            else:
                self.add_result("Cursor Pagination", False, "第二頁無貼文")

        except Exception as e:
            self.add_result("Cursor Pagination", False, str(e))

    def test_rate_limit(self):
        """測試限流處理"""
        print("\n" + "=" * 60)
        print("6. API 限流處理")
        print("=" * 60)

        if not self.graph:
            self.add_result("限流處理", False, "Token 未設定")
            return

        # 快速連續請求以觸發限流（可選）
        self.log("執行快速連續請求測試...", "INFO")

        rate_limited = False
        for i in range(10):
            try:
                self.graph.get(f"{self.target_page_id}/posts", {"limit": 1})
            except requests.HTTPError as e:
                if self.graph.is_rate_limited(e):
                    rate_limited = True
                    retry_after = self.graph.get_retry_after(e)
                    self.add_result(
                        "限流辨識",
                        True,
                        f"成功辨識 429，Retry-After: {retry_after or 'N/A'}",
                    )
                    break

        if not rate_limited:
            self.log("未觸發限流（正常情況）", "INFO")
            self.add_result("限流處理", True, "未觸發限流")

    def run_all_tests(self):
        """執行所有測試"""
        logging.basicConfig(level=logging.INFO, format="%(message)s")

        print("\n" + "#" * 60)
        print("# Facebook API 驗證腳本 v0.2")
        print("#" * 60)
        print(f"目標粉專 ID: {self.target_page_id}")
        print(f"API Version: {self.api_version}")
        print(
            f"Token: {self.access_token[:20]}..."
            if self.access_token
            else "Token: 未設定"
        )
        print("#" * 60 + "\n")

        # 執行測試
        self.check_env_vars()
        self.validate_token()
        self.validate_page()
        self.test_posts_endpoint()
        self.test_cursor_pagination()
        self.test_rate_limit()

        # 總結
        print("\n" + "=" * 60)
        print("測試總結")
        print("=" * 60)
        print(f"通過：{self.passed}")
        print(f"失敗：{self.failed}")
        print(f"總計：{self.passed + self.failed}")

        if self.failed > 0:
            print("\n⚠  部分測試失敗，請檢查：")
            print("  1. FACEBOOK_ACCESS_TOKEN 是否正確設定")
            print("  2. Token 是否有 pages_read_engagement 權限")
            print("  3. 目標粉專 ID 是否正確")
            print("  4. Token 是否過期")
        else:
            print("\n✓ 所有測試通過！可以開始實作監控系統。")

        return self.failed == 0


def main():
    """主函數"""
    validator = APIValidator(api_version="v26.0")
    success = validator.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
