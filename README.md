# Facebook 瀏覽器貼文監控

Chrome／Edge 擴充功能觀察使用者開啟的指定粉專頁面，交由本機 Python 服務儲存、去重，再以 Telegram／LINE／Email 通知。瀏覽器模式不需要 Facebook Access Token 或 PPCA。

## 快速開始

1. 安裝 Python 3.10+，執行 `python -m pip install -r requirements.txt`。
2. 編輯 `config.yaml` 中的目標粉專網址、ID 與通知管道；將通知憑證存入 `.env`。
3. 在專案目錄執行 `python -X utf8 main.py`（Windows Conda 使用 `conda run --live-stream -n facebook-monitor python -X utf8 main.py`）。
4. 在 Chrome／Edge 擴充功能管理頁開啟開發人員模式，載入本專案 `extension` 資料夾。
5. 將啟動時產生的 `browser-token.local` 配對碼貼入擴充功能。
6. 開啟目標粉專，瀏覽舊貼文建立基準，再按「基準確認，開始通知」。

完整操作與驗收方式：[瀏覽器安裝指南](BROWSER_SETUP.md)。

## 行為

- 首次觀察不通知，需明確啟用；基準與貼文 ID 持久化於 SQLite。
- 寫入貼文與待發通知使用單一交易；每個通知管道獨立追蹤及重試。
- 本機接收器只綁定 `127.0.0.1:8765`，要求隨機配對碼；不收集 Cookie 或 Facebook Token。
- 只處理設定目標的可辨識貼文連結，不會自動刷新、捲動或呼叫 Facebook 私有 API。
- popup 顯示連線、通知狀態、累計篇數及最近收到觀察的時間。

**這是首次看見的貼文通知，不是完整的新發文監控。** 舊文首次載入仍可能通知；關閉或休眠分頁後會停止觀察。只支援桌面版粉專首頁與一般貼文 permalink，Reels、限時動態與社團不支援。實際 Facebook 版面變更可能使解析失效。

## 測試

```powershell
python -X utf8 -m unittest discover -s tests -v
node --test extension/*.test.cjs
```

GitHub Actions 執行 Python 測試及擴充功能離線測試。實際 Facebook 頁面和通知收訊需另行驗收，離線測試不代表已通過線上驗收。

## 模組

- `extension/`：Manifest V3 擴充功能、貼文辨識、配對與狀態面板。
- `src/browser_receiver.py`：本機接收、目標驗證、基準與交易。
- `src/database.py`：SQLite 資料與通知佇列。
- `src/notifier.py`：Apprise／LINE 通知與重試。
- `src/scheduler.py`：通知排程。

原有 Graph API 工具與測試保留供獨立 API 診斷，主程式不會將它們當作瀏覽器失敗時的替代路徑。舊版設計文件中的 Graph API 啟動說明不適用於本版本。

## 開發參考

[Chrome 擴充功能跨來源請求](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests) · [Chrome storage](https://developer.chrome.com/docs/extensions/reference/api/storage)

本機憑證、配對碼與資料庫不可提交到 GitHub。
