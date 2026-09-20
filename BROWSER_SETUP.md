# 瀏覽器偵測安裝指南

這個版本觀察使用者正常瀏覽的 Facebook 粉專。不需要 Facebook Access Token 或 PPCA；不呼叫 Facebook 私有 API、不讀取登入 Cookie。只把指定頁面已載入且能辨識的貼文連結與文字摘要傳到自己電腦。

## 1. 啟動本機服務

在專案目錄執行：

```powershell
.venv\Scripts\python.exe -X utf8 main.py
# 或既有 Conda 環境
conda run --live-stream -n facebook-monitor python -X utf8 main.py
```

首次啟動自動產生 `browser-token.local`，這是擴充功能的配對碼（已被 `.gitignore` 的 `*.local` 排除）。服務固定監聽 `127.0.0.1:8765`，請保持終端機開啟，Ctrl+C 可停止。

`config.yaml` 的 `posts.source` 必須是 `browser`。目標設定需包含 `page_id`、`url`、`enabled: true`。URL 使用桌面版粉專首頁，如 `https://www.facebook.com/粉專帳號` 或 `https://www.facebook.com/profile.php?id=數字ID`。使用實際開啟後的網址；重新導向到不同帳號名稱時請同步更新設定並重啟服務。

## 2. 載入 Chrome / Edge 擴充功能

1. 開啟 `chrome://extensions` 或 `edge://extensions`。
2. 開啟「開發人員模式」，選「載入未封裝項目」。
3. 選擇本專案的 `extension` 資料夾。
4. 點工具列上的 Facebook Monitor Companion 圖示。
5. 將 `browser-token.local` 的內容貼到「本機配對碼」，按「儲存並連線」。
6. 顯示「本機服務已連線」後，點目標連結。若頁面在安裝前就已開啟，重新整理一次。

擴充功能透過 service worker 向本機傳送資料；配對碼只存在 extension storage 的 trusted contexts，不會傳給 Facebook 頁面。依據 [Chrome 跨來源請求文件](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests) 與 [storage 文件](https://developer.chrome.com/docs/extensions/reference/api/storage) 實作。

## 3. 建立基準，再啟用通知

1. 在粉專頁面正常瀏覽、捲動，等待至少 15 秒。
2. 擴充功能顯示「記錄基準（不通知）」與已記錄篇數；0 篇時不能啟用。
3. 確認已瀏覽希望排除的舊貼文後，按「基準確認，開始通知」。
4. 後續首次看見的貼文會加入通知佇列，現有排程器每 30 秒發送並處理失敗重試。
5. 「暫停通知」期間仍會記錄貼文，之後恢復不補發這些貼文。

首次看見不等於剛發布。通知會標示「瀏覽器首次看見；非發文時間」。捲到先前未載入的舊文仍可能產生通知；要回看歷史內容，先暫停通知。基準與去重狀態存在 SQLite，重新整理分頁或重啟程式不會清除。

## 4. 設定通知

在 `.env` 設定自己的通知憑證，並在 `config.yaml` 啟用管道，例如：

```yaml
notifications:
  timezone: Asia/Taipei
  channels:
    - id: telegram_main
      backend: apprise
      url_env: TELEGRAM_APPRISE_URL
```

`.env`：`TELEGRAM_APPRISE_URL=tgram://BOT_TOKEN/CHAT_ID`。LINE 沿用專案的 `backend: line`、`token_env` 與 `recipient_env`。預設 `channels: []` 只儲存，不發通知。設定變更後重啟 Python。

## 觀察範圍與故障排除

- 每 15 秒檢查一次目前 DOM，不會自動刷新、捲動、登入或打開背景分頁。Facebook 沒載入的新內容就看不到。
- 僅支援 `www.facebook.com` 粉專首頁、頁面內 `/帳號/posts/ID`、`permalink.php` 與 `story.php` 連結。Reels、影片獨立頁、限時動態、社團、首頁動態不支援。
- 只有明確屬於設定目標的 permalink 才送出；辨識不到會略過。DOM 結構改版可能需要更新 parser。
- 目前文字摘要只讀取明確的訊息區塊；找不到時傳連結，不抓整篇留言區。
- 關閉、休眠或凍結分頁會停止觀察。popup 的「最近收到」長時間不更新，應檢查分頁、登入狀態及本機服務。
- 連線失敗時，待送批次保留於該分頁記憶體並重試；分頁關閉／導向其他頁面會失去尚未確認的批次。已入庫通知不受影響，仍可由 Python 重試。
- 這是使用者瀏覽輔助工具，不保證全天候、完整收集，也不聲稱瀏覽器方式獲得 Meta 的自動資料收集許可。

## 驗收

```powershell
.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
node --test extension/parser.test.cjs
```

離線測試涵蓋基準、暫停、重啟去重、交易回滾、認證、錯誤來源／目標與連結解析。實際 Facebook DOM 及真實 Telegram／LINE 收訊，需以使用者自己的瀏覽器和管道驗收：先基準、再觀察未見貼文、确认只收一則，重新整理後不得重複通知。
