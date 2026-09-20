# 背景瀏覽器安裝與驗收

## 執行條件

電腦必須保持喚醒，Python 背景程序持續運行。日常 Facebook 分頁可以關閉。Windows 檢查使用已安裝 Edge 搭配專案獨立的工作階段；不需要 Facebook Access Token 或 PPCA，也不代表取得平台自動收集授權。

所有命令在專案目錄執行。無視窗啟動器使用專案的 `.venv`，需要 Windows Script Host 可用；不會變更 Windows 的指令碼安全設定，也不自動安裝開機啟動工作。

## 安裝與登入

```powershell
powershell -File scripts/setup-background.ps1
.venv\Scripts\python.exe -X utf8 main.py login
```

安裝腳本只建立／使用專案虛擬環境，確認 Edge 已安裝，不另外下載瀏覽器。首次登入由你自行輸入帳密、OTP／驗證碼。完成後保持瀏覽器開著，回到終端機按 Enter，程式會關閉視窗。Linux 測試環境使用 `python -m playwright install --with-deps chromium --no-shell` 安裝測試用 Chromium。

登入命令只保存工作階段；是否真能讀到目標內容要由背景檢查確認。遇到 checkpoint、登入表單或 HTTP 401／403，記錄 `login_required: true` 並暫停後續讀取。不要反覆重新啟動試圖略過驗證。

## 設定

```yaml
posts:
  source: background_browser
  interval_seconds: 300
targets:
  - page_id: "你的數字粉專ID"
    url: "https://www.facebook.com/粉專帳號"
    enabled: true
notifications:
  timezone: Asia/Taipei
  channels:
    - id: telegram_main
      backend: apprise
      url_env: TELEGRAM_APPRISE_URL
```

URL 支援桌面版粉專首頁或 `profile.php?id=數字ID`。背景開啟後若導向不同的粉專 URL，會記錄 `target_redirected`；請核對後更新設定。每輪間隔從上輪完成時計算，最少 60 秒，不追趕電腦休眠期間漏掉的排程。

通知憑證自行建立在 `.env`，例如 `TELEGRAM_APPRISE_URL=tgram://BOT_TOKEN/CHAT_ID`。LINE 使用現有 `backend: line`、`token_env`、`recipient_env` 設定。未啟用管道時只儲存。

## 啟動、基準、停止

- 雙擊 `start-background.vbs`：以 pythonw 啟動，不顯示主控台。
- `python main.py check`：手動執行一輪無頭讀取與待發通知處理。
- `python main.py status`：列出狀態、目標基準、觀察數與資源取樣。
- `python main.py enable 粉專ID`：觀察至少一篇後，明確啟用該目標的新觀察通知。
- `python main.py pause 粉專ID`：繼續記錄該目標，暫停為新觀察建立通知；已排入佇列的通知仍會發送。
- 雙擊 `stop-background.vbs` 或執行 `python main.py stop`：要求正常停止，不殺死日常瀏覽器。停止可能需要等待當前頁面請求／通知發送逾時。

以上 `python` 請使用專案 `.venv\Scripts\python.exe -X utf8`。背景模式不需安裝擴充功能、不再使用 localhost 接收器。不要同時開啟登入和監控，程序鎖會阻止共用專用設定檔。

## 狀態與資源

日誌在 `.runtime.local/monitor.log`，會輪替；不彈出錯誤視窗。狀態儲存在 SQLite：

| 欄位／狀態 | 意義 |
| --- | --- |
| `process_active` | 即時檢查專案程序鎖是否被登入／監控程序持有；不是讀取成功的證明 |
| `phase` | checking、idle、login_required、stopped 或 login_saved_unverified |
| `heartbeat_at` | 主迴圈最近運行時間；不是完整粉專檢查成功證明 |
| `login_required` | 需要人工登入／確認存取資格，背景讀取已暫停 |
| `target:ID.status` | observed 或 unavailable 等該目標的最近結果 |
| `no_recognizable_posts` | 可能是版面變更、內容未載入或存取問題；不當成無新貼文 |
| `resources.rss_mb_sample` | 取樣時 Python 及子程序 RSS 總和；不是峰值，可能重複計入共享記憶體 |
| `resources.cpu_seconds_sample` | 取樣時存活程序累計 CPU 秒數，不是 CPU 使用百分比 |
| `cycle_seconds` | 最近一輪執行時間 |

瀏覽器每輪結束關閉，閒置期間只剩 Python。資源取樣並非完整效能測試，不承諾特定 MB 或百分比。啟動失敗時檢查日誌及安裝；若政策禁止執行 VBS，需由使用者選擇允許的背景啟動方式。

## 登入失效處理

停止監控 → 確認狀態 stopped → 手動執行 login → 完成登入並按 Enter → 重新啟動。這是唯一會開可見視窗的使用者操作。背景讀取不會切換為可見瀏覽器，也不自動操作登入驗證。

## 驗收界線

2026-09-20 本機驗證：69 項 Python 單元測試、4 項 JavaScript parser 測試通過；Edge 無頭合成 DOM 整合測試與 pythonw 隱藏執行測試通過。未使用真實 Facebook 登入工作階段，通知發送以 mock 驗證；尚無真實粉專長時間 CPU／記憶體驗收數據。

目前階段規劃：先完成單一粉專的真實登入與 `check` 驗證，再確認實際通知和重複去重，最後連續量測數輪 CPU、記憶體及耗時。這三項完成前，背景模式仍視為原型，不宣稱全天候或零漏報。

離線測試與合成 DOM smoke test 不代表 Facebook 實機成功。正式使用前必須用自己的工作階段確認：

1. 首次讀取指定粉專成功，建立基準但不發通知。
2. 啟用後，首次看到另一篇可辨識貼文，通知真實送達；再次看到不重複建立通知。
3. 不開日常 Facebook 分頁也能讀取，且檢查期間沒有可見視窗或焦點切換。
4. 量測至少數輪 CPU、記憶體及耗時，確認符合可接受負擔。
5. 登入失效後暫停，狀態可查，沒有自動登入彈窗。

目前只讀每次首頁載入且可辨識的最多 50 篇，不自動捲動。舊文首次看見也可能通知；Reels、限時動態、獨立影片頁與社團不支援。5 分鐘不是發布到送達保證；缺漏、權限、版面與排序均影響結果。
