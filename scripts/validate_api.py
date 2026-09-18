#!/usr/bin/env python3
"""Facebook API 驗證腳本

此腳本用於驗證：
1. Meta App ID 與 Access Token 是否有效
2. 目標粉專 ID 是否正確且可讀取
3. 能否取得貼文並篩選指定作者
4. API 權限是否足夠

使用方式：
    python scripts/validate_api.py
    
環境變數要求：
    FACEBOOK_APP_ID
    FACEBOOK_PAGE_ACCESS_TOKEN
    FACEBOOK_USER_ACCESS_TOKEN (可選)
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

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
    print("警告：python-dotenv 未安裝，請執行：pip install python-dotenv")


class APIValidator:
    """Facebook API 驗證器"""
    
    def __init__(self):
        self.app_id = os.getenv('FACEBOOK_APP_ID')
        self.page_token = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
        self.user_token = os.getenv('FACEBOOK_USER_ACCESS_TOKEN')
        self.api_base = 'https://graph.facebook.com/v21.0'
        
        # 目標粉專 ID（可依環境變數覆蓋）
        self.target_page_id = os.getenv(
            'TARGET_PAGE_ID',
            '100054441671873'
        )
        
        self.results = []
        self.passed = 0
        self.failed = 0
    
    def log(self, message: str, level: str = 'INFO'):
        """記錄訊息"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [{level}] {message}")
    
    def add_result(self, test_name: str, passed: bool, message: str = ''):
        """記錄測試結果"""
        status = '✓ PASS' if passed else '✗ FAIL'
        self.results.append({
            'test': test_name,
            'passed': passed,
            'message': message
        })
        
        if passed:
            self.passed += 1
            print(f"  {status}: {test_name}")
        else:
            self.failed += 1
            print(f"  {status}: {test_name}")
            if message:
                print(f"         {message}")
    
    def check_env_vars(self):
        """檢查環境變數是否設定"""
        print("\n" + "="*60)
        print("1. 環境變數檢查")
        print("="*60)
        
        # App ID
        if self.app_id:
            self.add_result('FACEBOOK_APP_ID', True, f"已設定：{self.app_id[:10]}...")
        else:
            self.add_result('FACEBOOK_APP_ID', False, "未設定")
        
        # Page Access Token
        if self.page_token:
            self.add_result('FACEBOOK_PAGE_ACCESS_TOKEN', True, f"已設定：{self.page_token[:20]}...")
        else:
            self.add_result('FACEBOOK_PAGE_ACCESS_TOKEN', False, "未設定")
        
        # User Access Token (可選)
        if self.user_token:
            self.add_result('FACEBOOK_USER_ACCESS_TOKEN', True, f"已設定：{self.user_token[:20]}...")
        else:
            self.log("FACEBOOK_USER_ACCESS_TOKEN 未設定（可選）", "WARNING")
    
    def validate_token(self):
        """驗證 Access Token 是否有效"""
        print("\n" + "="*60)
        print("2. Access Token 驗證")
        print("="*60)
        
        if not self.page_token:
            self.add_result('Token 驗證', False, "Token 未設定")
            return
        
        try:
            url = f"{self.api_base}/debug_token"
            params = {
                'input_token': self.page_token,
                'access_token': self.user_token or self.page_token
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'data' in data:
                token_data = data['data']
                is_valid = token_data.get('is_valid', False)
                
                if is_valid:
                    self.add_result('Token 有效性', True)
                    
                    # 檢查到期時間
                    if 'expires_at' in token_data:
                        expires_at = token_data['expires_at']
                        try:
                            exp_time = datetime.fromtimestamp(int(expires_at))
                            days_left = (exp_time - datetime.now()).days
                            self.log(f"Token 剩餘有效天數：{days_left} 天", "INFO")
                        except:
                            self.log(f"Token 到期時間：{expires_at}", "INFO")
                    else:
                        self.log("Token 為永久有效或無到期時間", "INFO")
                    
                    # 檢查權限
                    if 'data' in token_data:
                        permissions = token_data.get('data', {}).get('permissions', [])
                        if permissions:
                            self.log(f"Token 權限：{', '.join(p.get('permission') for p in permissions if isinstance(p, dict))}", "INFO")
                        else:
                            permissions = token_data.get('permissions', [])
                            if permissions:
                                self.log(f"Token 權限：{', '.join(permissions)}", "INFO")
                else:
                    error_reason = token_data.get('error', {}).get('error_msg', 'Token 無效')
                    self.add_result('Token 有效性', False, error_reason)
            else:
                self.add_result('Token 驗證', False, "API 回應格式異常")
                self.log(f"回應：{json.dumps(data, indent=2)}", "DEBUG")
                
        except requests.exceptions.RequestException as e:
            self.add_result('Token 驗證', False, f"請求失敗：{e}")
        except Exception as e:
            self.add_result('Token 驗證', False, f"驗證失敗：{e}")
    
    def validate_page(self):
        """驗證目標粉專是否可讀取"""
        print("\n" + "="*60)
        print("3. 目標粉專驗證")
        print("="*60)
        
        if not self.page_token:
            self.add_result('粉專讀取', False, "Token 未設定")
            return
        
        try:
            url = f"{self.api_base}/{self.target_page_id}"
            params = {
                'access_token': self.page_token,
                'fields': 'id,name,username,category,verification_status'
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'id' in data:
                    self.add_result('粉專 ID 有效性', True)
                    
                    # 顯示粉專資訊
                    page_name = data.get('name', '未知')
                    page_username = data.get('username', '無')
                    page_category = data.get('category', '未知')
                    is_verified = data.get('verification_status', False)
                    
                    self.log(f"粉專名稱：{page_name}", "INFO")
                    self.log(f"使用者名稱：{page_username}", "INFO")
                    self.log(f"類別：{page_category}", "INFO")
                    self.log(f"驗證狀態：{'已驗證' if is_verified else '未驗證'}", "INFO")
                else:
                    self.add_result('粉專讀取', False, "回應缺少 id 欄位")
            elif response.status_code == 400:
                # 可能是 ID 格式錯誤或無效
                self.add_result('粉專 ID 有效性', False, "ID 可能無效或格式錯誤")
            elif response.status_code == 401:
                # 權限不足
                self.add_result('粉專讀取權限', False, "Access Token 權限不足")
            elif response.status_code == 403:
                # 被禁止存取
                self.add_result('粉專讀取權限', False, "無權存取此粉專（可能需要 Page Public Content Access 審核）")
            else:
                self.add_result('粉專讀取', False, f"HTTP {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            self.add_result('粉專讀取', False, f"請求失敗：{e}")
        except Exception as e:
            self.add_result('粉專讀取', False, f"驗證失敗：{e}")
    
    def test_feed_access(self):
        """測試能否讀取粉專貼文 feed"""
        print("\n" + "="*60)
        print("4. 貼文 Feed 讀取測試")
        print("="*60)
        
        if not self.page_token:
            self.add_result('Feed 讀取', False, "Token 未設定")
            return
        
        try:
            url = f"{self.api_base}/{self.target_page_id}/feed"
            params = {
                'access_token': self.page_token,
                'fields': 'id,author,created_time,message,type',
                'limit': 5
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'data' in data:
                    posts = data['data']
                    post_count = len(posts)
                    
                    self.add_result('Feed 讀取', True, f"成功取得 {post_count} 則貼文")
                    
                    if post_count > 0:
                        # 檢查第一則貼文的作者
                        first_post = posts[0]
                        author = first_post.get('author', {})
                        author_id = author.get('id') if author else None
                        
                        self.log(f"第一則貼文 ID: {first_post.get('id')}", "INFO")
                        self.log(f"第一則貼文作者 ID: {author_id}", "INFO")
                        self.log(f"目標粉專 ID: {self.target_page_id}", "INFO")
                        
                        if author_id == self.target_page_id:
                            self.add_result('作者篩選', True, "貼文作者與目標粉專一致")
                        else:
                            self.add_result('作者篩選', False, "貼文作者與目標粉專不一致（可能是訪客貼文）")
                    
                    # 顯示分頁資訊
                    paging = data.get('paging', {})
                    if 'next' in paging:
                        self.log("有分頁：可讀取更多貼文", "INFO")
                    else:
                        self.log("無更多分頁", "INFO")
                else:
                    self.add_result('Feed 讀取', False, "回應無 data 欄位")
            elif response.status_code == 400:
                self.add_result('Feed 讀取', False, "API 參數錯誤")
            elif response.status_code == 401:
                self.add_result('Feed 讀取權限', False, "Access Token 無效或過期")
            elif response.status_code == 403:
                self.add_result('Feed 讀取權限', False, "無權讀取此粉專的貼文（可能需要 Page Public Content Access）")
            else:
                self.add_result('Feed 讀取', False, f"HTTP {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            self.add_result('Feed 讀取', False, f"請求失敗：{e}")
        except Exception as e:
            self.add_result('Feed 讀取', False, f"測試失敗：{e}")
    
    def test_author_filtering(self):
        """測試作者篩選邏輯"""
        print("\n" + "="*60)
        print("5. 作者篩選邏輯測試")
        print("="*60)
        
        if not self.page_token:
            self.add_result('作者篩選', False, "Token 未設定")
            return
        
        try:
            url = f"{self.api_base}/{self.target_page_id}/feed"
            params = {
                'access_token': self.page_token,
                'fields': 'id,author{id,name},created_time,message,type',
                'limit': 20
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            all_posts = data.get('data', [])
            target_posts = []
            other_posts = []
            
            for post in all_posts:
                author = post.get('author', {})
                author_id = author.get('id') if author else None
                
                if author_id == self.target_page_id:
                    target_posts.append(post)
                else:
                    other_posts.append(post)
            
            self.log(f"總貼文數：{len(all_posts)}", "INFO")
            self.log(f"目標粉專發布：{len(target_posts)}", "INFO")
            self.log(f"其他作者（訪客等）：{len(other_posts)}", "INFO")
            
            if len(all_posts) > 0:
                if len(target_posts) > 0:
                    self.add_result('作者篩選', True, f"成功篩選出 {len(target_posts)} 則目標粉專貼文")
                else:
                    self.add_result('作者篩選', False, "未找到目標粉專發布的貼文")
            else:
                self.add_result('作者篩選', False, "無貼文可測試")
                
        except Exception as e:
            self.add_result('作者篩選', False, f"測試失敗：{e}")
    
    def run_all_tests(self):
        """執行所有測試"""
        print("\n" + "#"*60)
        print("# Facebook API 驗證腳本")
        print("#"*60)
        print(f"目標粉專 ID: {self.target_page_id}")
        print(f"目標網址：https://www.facebook.com/profile.php?id={self.target_page_id}")
        print("#"*60 + "\n")
        
        # 執行測試
        self.check_env_vars()
        self.validate_token()
        self.validate_page()
        self.test_feed_access()
        self.test_author_filtering()
        
        # 總結
        print("\n" + "="*60)
        print("測試總結")
        print("="*60)
        print(f"通過：{self.passed}")
        print(f"失敗：{self.failed}")
        print(f"總計：{self.passed + self.failed}")
        
        if self.failed > 0:
            print("\n⚠  部分測試失敗，請檢查：")
            print("  1. 環境變數是否正確設定")
            print("  2. Access Token 是否有效且未過期")
            print("  3. Token 是否有足夠權限（Page Public Content Access）")
            print("  4. 目標粉專 ID 是否正確")
            print("\n詳細資訊請參閱上方測試結果")
        else:
            print("\n✓ 所有測試通過！可以開始實作監控系統。")
        
        return self.failed == 0


def main():
    """主函式"""
    validator = APIValidator()
    success = validator.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
