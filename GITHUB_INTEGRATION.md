# Facebook 監控：背景靜默運行與 GitHub 整合指引

本專案專為「**背景極致輕量、零彈窗干擾（除通知外）、不影響使用者電腦操作**」而設計，並提供與 **GitHub** 的全方位搭配整合方案。

---

## 雙軌架構模式比較

| 項目 | 模式 A：本機靜默常駐 + GitHub 託管（推薦） | 模式 B：GitHub Actions 雲端定時排程 |
| :--- | :--- | :--- |
| **運行環境** | 使用者 Windows 本機背景（`pythonw` / 工作排程器） | GitHub 雲端伺服器（Ubuntu Runner） |
| **電腦需開機** | 需開機（登入後自動背景常駐） | 電腦完全不需開機 |
| **電腦干擾程度** | **完全無感**（無終端機、無視窗、不搶焦點） | **零本機資源消耗** |
| **Facebook 穩定度** | **高**（使用家用住宅 IP 與本機 Edge 登入工作階段，不易被 FB 阻擋） | **低至中**（微軟 Azure 機房 IP 易遭 FB 嚴格反爬蟲、驗證碼或登入牆封鎖） |
| **通知方式** | 遠端推播（Telegram、LINE、Discord、Email 等） | 遠端推播（Telegram、LINE、Discord、Email 等） |
| **適用情境** | 日常辦公/遊戲電腦，需穩定可靠且無彈窗監控粉專 | 免開機雲端實驗、伺服器排程測試 |

---

## 模式 A：本機極致靜默常駐（推薦最佳實踐）

### 1. 核心無感機制說明
- **全無視窗**：透過 `pythonw.exe` 執行，完全不開啟 CMD 或 PowerShell 黑色主控台視窗。
- **極低資源損耗**：使用獨立無頭（Headless）Edge 瀏覽器，自動阻擋圖片、影片及字型下載；每一輪檢查僅耗時數秒，檢查完畢**立即徹底關閉瀏覽器釋放所有 CPU 與記憶體**。
- **異常不彈窗**：若遇到 Facebook 登入過期、網路連線逾時或任何錯誤，程式僅會寫入本機日誌與資料庫狀態，**絕不彈出錯誤對話框或瀏覽器視窗**。
- **通知不干擾電腦**：新貼文直接透過通訊軟體或外部管道（Telegram / LINE / Discord / Email）傳送，電腦桌面保持完全乾淨，不彈出任何視窗、不搶焦點、不干擾使用者操作。

### 2. 快速設定與一鍵開機自啟

#### 第一步：安裝環境與登入（僅首次需要）
```powershell
# 1. 初始化虛擬環境與套件
powershell -File scripts/setup-background.ps1

# 2. 進行首次登入（這是唯一會開啟可見瀏覽器的步驟）
.venv\Scripts\python.exe -X utf8 main.py login
```
*在開啟的 Edge 視窗中登入您的 Facebook 帳號，完成後回到終端機按 Enter 關閉。*

#### 第二步：設定監控目標與通知方式
編輯專案根目錄下的 `config.yaml`：
```yaml
# 監控目標
targets:
  - page_id: "目標粉專ID"
    url: "https://www.facebook.com/目標粉專帳號"
    enabled: true

# 啟用通知管道（可依需求配置）
notifications:
  timezone: Asia/Taipei
  channels:
    # 範例：Telegram Bot 推播
    - id: telegram_main
      backend: apprise
      url_env: TELEGRAM_APPRISE_URL

    # 範例：LINE Messaging API 推播
    - id: line_main
      backend: line
      token_env: LINE_CHANNEL_ACCESS_TOKEN
      recipient_env: LINE_TO
```
若使用 Telegram / LINE 等，請在 `.env` 中填入憑證（如 `TELEGRAM_APPRISE_URL=tgram://BOT_TOKEN/CHAT_ID`）。

#### 第三步：一鍵註冊開機靜默啟動（工作排程器）
在 PowerShell 中執行：
```powershell
powershell -File scripts/setup-task-scheduler.ps1
```
- 腳本會自動將程式註冊至 Windows 工作排程器（名為 `FacebookMonitor`）。
- 每次開機登入 Windows 後，將自動在背景靜默運行，無任何彈窗干擾。
- **查詢狀態**：`powershell -File scripts/setup-task-scheduler.ps1 -Status`
- **解除排程**：`powershell -File scripts/setup-task-scheduler.ps1 -Uninstall`

---

## 模式 B：搭配 GitHub Actions 雲端排程

專案已內建 [`.github/workflows/scheduled-monitor.yml`](.github/workflows/scheduled-monitor.yml)，可直接利用 GitHub 免費 Actions 額度進行定時檢查。

### 1. 設定 GitHub Repository Secrets
前往您的 GitHub 專案頁面：`Settings` → `Secrets and variables` → `Actions` → `New repository secret`，新增以下金鑰（依您使用的通知管道而定）：
- `TELEGRAM_APPRISE_URL`：例如 `tgram://BOT_TOKEN/CHAT_ID`
- `LINE_CHANNEL_ACCESS_TOKEN` 與 `LINE_TO`（若使用 LINE）
- `DISCORD_APPRISE_URL`（若使用 Discord Webhook）

### 2. 運作與排程設定
- 預設排程為每 30 分鐘自動執行一次（可於 `.github/workflows/scheduled-monitor.yml` 中修改 `cron` 表達式）。
- 亦可在 GitHub 網頁的 **Actions** 分頁點選 **Scheduled Facebook Monitor** → **Run workflow** 進行手動即時測試。
- 每次執行會自動透過 `actions/cache` 保存 `monitor.sqlite3`，確保貼文不會重複發送通知。

### 3. 雲端環境限制說明
> [!WARNING]
> Facebook 對雲端伺服器（GitHub Actions 使用之 Microsoft Azure IP）有嚴格的風控偵測：
> - 未登入之公開粉專亦可能被頻繁導向登入牆或要求填寫 CAPTCHA 驗證碼。
> - 若需要最高可靠性，仍強烈建議採用 **模式 A（本機靜默常駐）**，讓本機住宅 IP 自然避免此類機房封鎖。

---

## 安全與版本控制守則

1. **不可提交機密至 GitHub**：
   - `.env`（通訊軟體憑證）
   - `.runtime.local/`（瀏覽器登入 Session 與日誌）
   - `monitor.sqlite3`（本機歷史貼文與狀態快取）
   - 上述項目已全數列於 `.gitignore`，確保您 push 代碼至 GitHub 時不會洩漏個人 Facebook 隱私與 Token。
2. **日常健康檢查**：
   隨時可於終端機執行下列指令檢查監控運作與基準狀態：
   ```powershell
   .venv\Scripts\python.exe -X utf8 main.py status
   ```
