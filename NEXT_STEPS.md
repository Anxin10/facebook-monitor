# 下一步開發與驗證指引

本文檔說明 Facebook 輕量背景監控系統（3.0 版）的驗證與執行優先順序，確保符合「**背景輕量運行、不影響電腦操作、除通知外零彈窗、搭配 GitHub**」之核心需求。

---

## 📌 當前架構狀態

| 模組 | 狀態 | 說明 |
| --- | --- | --- |
| **無頭背景讀取** | ✅ 完成 | 獨立設定檔、Edge 無頭執行、自動攔截圖片/影音/字型，每輪結束釋放瀏覽器 |
| **程序隔離與零彈窗** | ✅ 完成 | `pythonw.exe` 運行，錯誤/驗證失效只記日誌不彈窗，僅手動 `login` 開啟瀏覽器 |
| **資料庫與去重** | ✅ 完成 | SQLite 單一交易提交基準、貼文去重與通知佇列 |
| **通知發送器** | ✅ 完成 | 支援 Telegram、LINE、Discord、Email 等多管道推播，電腦桌面保持無彈窗 |
| **開機自啟排程** | ✅ 完成 | `scripts/setup-task-scheduler.ps1` 一鍵註冊/移除 Windows 工作排程器 |
| **GitHub 整合** | ✅ 完成 | 提供 GitHub Actions 雲端定時排程（`.github/workflows/scheduled-monitor.yml`）與完整說明 |
| **限時動態監控** | ⏸️ 暫停 | 因 Facebook 介面限制與保護帳號考量，目前維持關閉 |

---

## 🎯 優先順序 P0（使用者初次上線驗收）

### 1. 本機環境初始化與首次登入
**目標**：建立專案專屬的 Facebook 登入工作階段（不影響日常瀏覽器）。

**步驟：**
1. 執行依賴安裝：
   ```powershell
   powershell -File scripts/setup-background.ps1
   ```
2. 執行首次手動登入（這是唯一會開可見瀏覽器的步驟）：
   ```powershell
   python -X utf8 main.py login
   ```
   *於彈出的視窗中登入 Facebook，完成後回到終端機按 Enter 關閉。*

### 2. 設定目標與通知管道
**目標**：確認監控粉專與接收通知的方式。

**步驟：**
1. 編輯 `config.yaml`：
   - 填入目標 `page_id` 與 `url`。
   - 啟用通知管道（例如 Telegram、LINE 或 Discord）。
2. 若使用通訊軟體，於 `.env` 設定對應憑證。

---

## 🎯 優先順序 P1（建立基準與無感常駐）

### 3. 首次觀察建立基準
**目標**：建立目標粉專既有貼文的基準，避免啟動時被大量舊貼文洗版。

**步驟：**
1. 手動執行一次檢查：
   ```powershell
   python -X utf8 main.py check
   ```
2. 查看狀態，確認目標已觀察到貼文（observed）：
   ```powershell
   python -X utf8 main.py status
   ```
3. 確認基準已建立後，正式啟用通知推播：
   ```powershell
   python -X utf8 main.py enable 目標粉專ID
   ```

### 4. 啟用 Windows 開機自啟無感背景運行
**目標**：讓監控程式在登入 Windows 時全靜默常駐，日常使用完全無感。

**步驟：**
1. 註冊 Windows 工作排程器：
   ```powershell
   powershell -File scripts/setup-task-scheduler.ps1
   ```
2. 驗證：
   - 工作管理員中可見 `pythonw.exe` 於背景執行。
   - 畫面上完全沒有任何黑視窗、命令列跳出，也不會搶佔滑鼠焦點。

---

## 🎯 優先順序 P2（GitHub 搭配與同步）

### 5. GitHub 儲存庫管理與 CI
**目標**：將專案安全推播至 GitHub 進行代碼版本控制。

**步驟：**
1. 確認敏感資訊（`.env`、`.runtime.local`、`monitor.sqlite3`）未被追蹤：
   ```powershell
   git status
   ```
2. 推送至遠端儲存庫：
   ```powershell
   git push origin main
   ```
3. 觀察 GitHub Actions 自動執行之單元測試與程式碼風格檢查。

### 6. （可選）GitHub Actions 雲端定時排程
**目標**：若希望免開機定時檢查，可啟用雲端排程。

**步驟：**
1. 於 GitHub 專案的 `Settings` → `Secrets and variables` → `Actions` 中設定通知憑證（例如 `TELEGRAM_APPRISE_URL`）。
2. 工作流 `.github/workflows/scheduled-monitor.yml` 將按排程定時自動執行。
3. *注意：雲端機房 IP 較易觸發 Facebook 驗證牆，若遇此情況建議以本機靜默常駐為主力。*

---

## 🎯 優先順序 P3（長期維護與監控）

- **登入狀態檢查**：偶爾執行 `main.py status` 確認是否需要重新驗證（`phase: login_required`）。
- **資源負擔評估**：透過 `status` 指令中的 `resources.rss_mb_sample` 與 `cycle_seconds` 確認系統負擔始終保持輕量。

---

## 參考文件
- 操作說明：[BROWSER_SETUP.md](BROWSER_SETUP.md)
- GitHub 整合：[GITHUB_INTEGRATION.md](GITHUB_INTEGRATION.md)
- 架構設計：[facebook-monitor-design.md](facebook-monitor-design.md)
- 歷史選型比較：[HYBRID_INTEGRATION.md](HYBRID_INTEGRATION.md)