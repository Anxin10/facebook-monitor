#!/usr/bin/env python3
"""Facebook 貼文讀取測試腳本

此腳本用於實際讀取粉專貼文並測試去重邏輯。
適合在 API 驗證通過後使用。

使用方式：
    python scripts/test_post_fetcher.py
    
環境變數要求：
    FACEBOOK_PAGE_ACCESS_TOKEN
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

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("警告：python-dotenv 未安裝")


class PostFetcherTester:
    """貼文讀取測試器"""
    
    def __init__(self):
        self.access_token = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
        self.api_base = 'https://graph.facebook.com/v21.0'
        self.target_page_id = os.getenv('TARGET_PAGE_ID', '100054441671873')
        
        # 模擬已存在的貼文 ID（用於測試去重）
        self.existing_ids = set()
    
    def log(self, message: str, level: str = 'INFO'):
        """記錄訊息"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [{level}] {message}")
    
    def fetch_posts(self, limit_pages: int = 3):
        """讀取貼文並測試去重邏輯"""
        if not self.access_token:
            print("錯誤：FACEBOOK_PAGE_ACCESS_TOKEN 未設定")
            return []
        
        print("\n" + "="*60)
        print("貼文讀取測試")
        print("="*60)
        print(f"目標粉專：{self.target_page_id}")
        print("="*60 + "\n")
        
        all_posts = []
        target_posts = []
        page_count = 0
        
        try:
            # 第一頁
            url = f"{self.api_base}/{self.target_page_id}/feed"
            params = {
                'access_token': self.access_token,
                'fields': 'id,author{id,name},created_time,message,story,full_picture,link,permalink_url,type,status_type',
                'limit': 25
            }
            
            self.log(f"讀取第 {page_count + 1} 頁...")
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # 處理第一頁
            posts = data.get('data', [])
            all_posts.extend(posts)
            
            for post in posts:
                author = post.get('author', {})
                author_id = author.get('id') if author else None
                
                if author_id == self.target_page_id:
                    target_posts.append(post)
            
            page_count += 1
            
            # 處理分頁
            paging = data.get('paging', {})
            while 'next' in paging and page_count < limit_pages:
                next_url = paging['next']
                page_count += 1
                
                self.log(f"讀取第 {page_count} 頁...")
                response = requests.get(next_url, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                posts = data.get('data', [])
                all_posts.extend(posts)
                
                for post in posts:
                    author = post.get('author', {})
                    author_id = author.get('id') if author else None
                    
                    if author_id == self.target_page_id:
                        target_posts.append(post)
                
                paging = data.get('paging', {})
            
            # 統計
            print("\n" + "="*60)
            print("讀取結果")
            print("="*60)
            print(f"總貼文數：{len(all_posts)}")
            print(f"目標粉專發布：{len(target_posts)}")
            print(f"其他作者：{len(all_posts) - len(target_posts)}")
            print(f"讀取頁數：{page_count}")
            
            # 測試去重
            print("\n" + "="*60)
            print("去重測試")
            print("="*60)
            
            unique_ids = set()
            new_posts = []
            existing_posts = []
            
            for post in target_posts:
                post_id = post.get('id')
                if post_id in self.existing_ids:
                    existing_posts.append(post)
                    print(f"  [已存在] {post_id}")
                elif post_id in unique_ids:
                    print(f"  [重複] {post_id}")
                else:
                    unique_ids.add(post_id)
                    new_posts.append(post)
                    if len(new_posts) <= 5:
                        print(f"  [新] {post_id}")
            
            if len(new_posts) > 5:
                print(f"  ... 還有 {len(new_posts) - 5} 則新貼文")
            
            print(f"\n新貼文：{len(new_posts)}")
            print(f"已存在：{len(existing_posts)}")
            
            # 顯示新貼文摘要
            if new_posts:
                print("\n" + "="*60)
                print("新貼文摘要（前 3 則）")
                print("="*60)
                
                for i, post in enumerate(new_posts[:3], 1):
                    print(f"\n{i}. ID: {post.get('id')}")
                    print(f"   時間：{post.get('created_time', '未知')}")
                    print(f"   類型：{post.get('type', 'unknown')}")
                    
                    message = post.get('message', '')
                    story = post.get('story', '')
                    
                    if message:
                        print(f"   內容：{message[:100]}..." if len(message) > 100 else f"   內容：{message}")
                    elif story:
                        print(f"   故事：{story[:100]}..." if len(story) > 100 else f"   故事：{story}")
                    else:
                        post_type = post.get('type', 'unknown')
                        type_map = {
                            'photo': '圖片',
                            'video': '影片',
                            'link': '連結',
                            'status': '文字'
                        }
                        print(f"   內容：{type_map.get(post_type, post_type)}")
                    
                    permalink = post.get('permalink_url', '')
                    if permalink:
                        print(f"   連結：{permalink}")
            
            return target_posts
            
        except requests.exceptions.RequestException as e:
            self.log(f"API 請求失敗：{e}", "ERROR")
            return []
        except Exception as e:
            self.log(f"測試失敗：{e}", "ERROR")
            return []
    
    def simulate_duplicate_check(self):
        """模擬重複檢查場景"""
        print("\n" + "="*60)
        print("模擬重複檢查")
        print("="*60)
        
        # 第一次讀取
        print("\n第一次讀取...")
        posts1 = self.fetch_posts(limit_pages=1)
        
        # 記錄已存在的 ID
        self.existing_ids = {post.get('id') for post in posts1}
        print(f"已記錄 {len(self.existing_ids)} 則貼文 ID")
        
        # 第二次讀取（模擬）
        print("\n第二次讀取（模擬）...")
        posts2 = self.fetch_posts(limit_pages=1)
        
        # 檢查是否有新貼文
        new_count = 0
        for post in posts2:
            if post.get('id') not in self.existing_ids:
                new_count += 1
        
        print(f"\n第二次讀取結果：")
        print(f"  新貼文：{new_count}")
        print(f"  已存在：{len(posts2) - new_count}")


def main():
    """主函式"""
    tester = PostFetcherTester()
    
    # 執行測試
    tester.fetch_posts()
    
    # 詢問是否進行重複檢查模擬
    print("\n" + "="*60)
    response = input("是否執行重複檢查模擬？(y/n): ").strip().lower()
    
    if response == 'y':
        tester.simulate_duplicate_check()


if __name__ == '__main__':
    main()
