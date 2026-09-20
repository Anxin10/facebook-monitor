# Facebook 背景貼文監控

使用獨立設定檔的無頭 Edge，每 5 分鐘依序讀取指定粉專已載入的貼文，保存到 SQLite，並透過 Telegram／LINE／Email 通知。平常不用開 Facebook 分頁；不操作你的日常瀏覽器，不開可見視窗或搶焦點。

這是背景讀取原型，尚未完成真實 Facebook 登入與通知收訊驗收。頁面改版、登入驗證與存取限制可能使讀取失敗；不保證完整收集或全天候可用。

## Windows 快速開始

1. 執行 `powershell -File scripts/setup-background.ps1` 安裝 Python 依賴並確認 Windows 已安裝 Edge。
2. 編輯 `config.yaml` 的目標與通知管道，通知憑證放在 `.env`。
3. 執行 `.venv\Scripts\python.exe -X utf8 main.py login`，自行登入後回終端機按 Enter。只有此指令會開可見瀏覽器。
4. 雙擊 `start-background.vbs`，無視窗啟動；每輪共用一個分頁，完成後釋放瀏覽器。
5. 執行 `.venv\Scripts\python.exe -X utf8 main.py status` 查看基準及健康狀態。
6. 首次成功觀察不通知。確認目標已有基準後，執行 `.venv\Scripts\python.exe -X utf8 main.py enable 你的粉專ID`。
7. 要停止時雙擊 `stop-background.vbs`。正在處理的請求需等到完成或逾時。

完整操作：[BROWSER_SETUP.md](BROWSER_SETUP.md)。架構與限制：[facebook-monitor-design.md](facebook-monitor-design.md)。

## 行為

- 登入設定檔固定在 `.runtime.local/profile`，不匯出 Cookie，不使用日常 Chrome／Edge 設定檔。
- 登入或驗證失效時停止後續讀取，不自動彈出登入頁；由你停止服務、手動登入、重新啟動。
- 一輪一個瀏覽器、一個分頁、逐粉專讀取；擋下圖片、影音及字型請求；每輪結束關閉瀏覽器。
- 低資源是設計目標，並非已達成固定記憶體上限。狀態提供程序樹 RSS／CPU 時間取樣與每輪耗時。
- 首次看見的舊文也可能通知；訊息不把觀察時間當成發布時間。
- 預設 `channels: []` 只儲存，不發送。基準、貼文去重和通知佇列沿用 SQLite。
- 已移除常開分頁的擴充功能與本機 HTTP 接收器。既有 SQLite 內容保留，不需要舊配對碼。

## 驗證

```powershell
.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
node --test tests/parser.test.cjs
.venv\Scripts\python.exe -X utf8 scripts/smoke-background.py
```

瀏覽器 smoke test 在真實瀏覽器中載入本機合成 DOM，測試解析→入庫→去重→模擬通知；所有頁面請求都攔截，不連 Facebook。Windows 使用 Edge，Linux CI 使用 Playwright Chromium。這不代表線上驗收已通過。

登入設定檔、配對憑證、資料庫與日誌不可上傳 GitHub。
