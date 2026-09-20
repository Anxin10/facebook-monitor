#!/usr/bin/env python3
"""測試通知發送腳本

用於驗證 .env 中的 LINE_TO、LINE_CHANNEL_ACCESS_TOKEN 是否設定正確，
並直接向指定的接收者（個人或群組）發送一則即時測試訊息。

使用方式：
    python scripts/test_notify.py
"""

import os
import sys
import json
import uuid
from datetime import datetime
from pathlib import Path

# 加入專案根目錄
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass

import requests

def test_line_push():
    print("=" * 60)
    print("🔔 LINE 推播設定測試")
    print("=" * 60)

    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    recipient_raw = os.getenv("LINE_TO")

    if not token:
        print("❌ 錯誤：.env 中未設定 LINE_CHANNEL_ACCESS_TOKEN")
        return False

    if not recipient_raw:
        print("❌ 錯誤：.env 中未設定 LINE_TO")
        return False

    recipients = [r.strip() for r in recipient_raw.split(",") if r.strip()]
    print(f"[*] 讀取到接收對象（共 {len(recipients)} 個）：")
    for r in recipients:
        target_type = "群組 (Group)" if r.startswith("C") or r.startswith("R") else "個人 (User)"
        print(f"    - {r} [{target_type}]")

    now_str = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    test_message = (
        f"🔔 Facebook 監控系統 - 連線測試\n"
        f"發送時間：{now_str}\n"
        f"狀態：LINE 推播管道運作正常！\n\n"
        f"（若您收到此訊息，代表接收者 ID 設定正確）"
    )

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    all_success = True
    for idx, recipient in enumerate(recipients):
        print(f"\n[*] 正在發送測試訊息至: {recipient} ...")
        retry_key = str(uuid.uuid4())
        headers["X-Line-Retry-Key"] = retry_key
        payload = {
            "to": recipient,
            "messages": [{"type": "text", "text": test_message}]
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if 200 <= resp.status_code < 300:
                req_id = resp.headers.get("x-line-request-id", "")
                print(f"  ✅ 發送成功！(HTTP {resp.status_code}, request_id={req_id})")
            else:
                all_success = False
                print(f"  ❌ 發送失敗！(HTTP {resp.status_code})")
                print(f"     回應內容: {resp.text}")
                if resp.status_code == 400:
                    print("     提示：若目標是群組（C 開頭），請確認已將 LINE 機器人邀請入群，且機器人具備加入群組權限。")
                elif resp.status_code == 401:
                    print("     提示：LINE_CHANNEL_ACCESS_TOKEN 可能已過期或錯誤。")
        except Exception as e:
            all_success = False
            print(f"  ❌ 連線異常: {e}")

    print("\n" + "=" * 60)
    if all_success:
        print("🎉 全部測試訊息發送成功！請查看手機 LINE 是否收到訊息。")
    else:
        print("⚠️ 部份或全部發送失敗，請依上方提示檢查。")
    print("=" * 60)
    return all_success

if __name__ == "__main__":
    test_line_push()
