# 測試與驗證指南

目前主程式使用背景無頭瀏覽器，安裝與實機驗收請參閱 [BROWSER_SETUP.md](BROWSER_SETUP.md)。
執行 `python -X utf8 -m unittest discover -s tests -v` 與 `node --test tests/parser.test.cjs`。
Windows 使用已安裝 Edge，Linux 先安裝 Playwright Chromium，再執行 `python scripts/smoke-background.py` 驗證合成 DOM 的解析、入庫與模擬通知。此測試不連 Facebook，也不能代替線上驗收。
下方 Graph API 驗證是獨立工具，不是瀏覽器模式的必要條件。

本文檔說明如何執行離線測試和線上驗證。

## 環境準備

### 1. 克隆專案

```bash
git clone https://github.com/Anxin10/facebook-monitor.git
cd facebook-monitor
git checkout fix/core-correctness
```

### 2. 建立虛擬環境

#### 方式 A：venv

```bash
# Python 3.10 以上
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

#### 方式 B：Conda

```bash
conda create -y -n facebook-monitor python=3.11
conda activate facebook-monitor
```

### 3. 安裝依賴

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

---

## 🔴 高優先級：離線測試

### 執行所有測試

```bash
# 使用測試運行腳本
python run_tests.py

# 或使用 unittest
python -m unittest discover -s tests -v
```

> **⚠️ Windows + Conda 使用者注意**
>
> 在 Windows 繁體中文環境（CP950）下，**請勿使用** `conda run -n facebook-monitor python run_tests.py`。
>
> Conda 25.x 的 `conda run` 會以 `Popen(text=True, errors="replace")` 捕獲子程序輸出，
> 並用系統預設編碼（CP950）解碼 UTF-8 bytes，導致 `UnicodeEncodeError` 崩潰。
>
> **正確做法（擇一）：**
> ```bash
> # 推薦：先啟用環境再執行
> conda activate facebook-monitor
> python run_tests.py
>
> # 或：使用 --live-stream 跳過 stdout 捕獲
> conda run --live-stream -n facebook-monitor python run_tests.py
> ```

### 預期結果

```
======================================================================
Facebook 監控系統 - 離線測試
======================================================================

測試摘要
============================================================
測試數量：48
失敗：0
錯誤：0
跳過：0

✅ 所有測試通過！
```

### 測試涵蓋項目

#### 資料庫測試（12 項）
- `test_init_database` - 資料庫初始化
- `test_add_item` - 新增內容項目
- `test_item_exists` - 內容存在檢查
- `test_duplicate_item_rejected` - 重複項目被拒絕（重啟去重）
- `test_author_filter` - 作者篩選
- `test_empty_baseline` - 空基準處理
- `test_baseline_ready` - 基準已建立標記
- `test_pagination_incomplete` - 分頁未完成標記
- `test_partial_failure_rollback` - 部分失敗回滾（交易回滾）
- `test_three_page_cursor` - 三頁游標分頁
- `test_notifications_by_channel` - 逐目的地通知
- `test_notification_retry` - 通知重試機制

#### 貼文讀取器測試（11 項）
- `test_from_id_author_filter` - 使用 from.id 判定作者
- `test_unknown_author_rejected` - 未知作者被拒絕
- `test_empty_result` - 空結果處理
- `test_pagination_cursor` - 分頁游標
- `test_pagination_limit` - 分頁上限
- `test_api_rate_limit` - API 限流處理
- `test_api_request_error` - API 請求錯誤
- `test_fixed_graph_host` - 固定 Graph host
- `test_since_parameter` - since 參數
- `test_prepare_item` - 準備 item 資料
- `test_prepare_item_missing_author` - 缺少作者的 item 被拒絕

#### 通知模組測試（7 項）
- `test_apprise_notification` - Apprise 通知呼叫
- `test_line_notification` - LINE 通知
- `test_line_retry_response` - LINE 重試回應
- `test_per_channel_retry` - 逐目的地重試
- `test_notification_message_format` - 通知訊息格式
- `test_timezone_handling` - 時區處理

---

## 🟡 中優先級：線上驗證

### 準備測試憑證

#### 1. Facebook Access Token

取得具有粉專讀取權限的 Access Token：

1. 前往 [Facebook Developers](https://developers.facebook.com/)
2. 建立應用程式（或使用現有的）
3. 使用 [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
4. 選擇你的粉專
5. 請求以下權限：
   - `pages_read_engagement`
   - `pages_manage_posts`（如需管理）
6. 複製生成的 Access Token

#### 2. Telegram Bot（可選）

1. 在 Telegram 搜尋 `@BotFather`
2. 發送 `/newbot` 建立新 Bot
3. 遵循指示設定名稱和使用者名稱
4. 複製返回的 Bot Token
5. 開啟與 Bot 的對話，使用 `@getmyid_bot` 取得 Chat ID

#### 3. LINE Channel（可選）

1. 前往 [LINE Developers](https://developers.line.biz/)
2. 建立 LINE 開發者帳號
3. 建立 Messaging API 頻道
4. 取得 Channel Access Token
5. 取得你的 LINE User ID

### 建立 .env 檔案

```bash
cp .env.example .env
```

編輯 `.env` 填入實際值：

```dotenv
# Facebook
FACEBOOK_ACCESS_TOKEN=EAAG...你的 Token

# Telegram（可選）
TELEGRAM_APPRISE_URL=tgram://你的 BOT_TOKEN/你的CHAT_ID

# LINE（可選）
LINE_CHANNEL_ACCESS_TOKEN=你的 LINE Token
LINE_TO=你的 LINE User ID
```

### 配置監控目標

編輯 `config.yaml`：

```yaml
targets:
  - page_id: "你的粉專 ID"
    url: "https://www.facebook.com/你的粉專"
    enabled: true

notifications:
  timezone: Asia/Taipei
  notify_existing_on_first_run: false  # 首次不通知既有內容
  channels:
    - id: telegram_main
      backend: apprise
      url_env: TELEGRAM_APPRISE_URL
    # - id: line_main
    #   backend: line
    #   token_env: LINE_CHANNEL_ACCESS_TOKEN
    #   recipient_env: LINE_TO
```

### 執行線上驗證

#### 1. 測試 Graph API 連線

```bash
python -c "
import os
import requests
from dotenv import load_dotenv

load_dotenv()

token = os.getenv('FACEBOOK_ACCESS_TOKEN')
page_id = '你的粉專 ID'

response = requests.get(
    f'https://graph.facebook.com/v21.0/{page_id}/feed',
    params={'access_token': token, 'limit': 5}
)

data = response.json()
print(f'Status: {response.status_code}')
print(f'Posts: {len(data.get(\"data\", []))}')
"
```

#### 2. 運行監控程式

```bash
python main.py
```

觀察日誌輸出：

```bash
tail -f monitor.log
```

### 驗證清單

- [ ] Graph API 貼文讀取成功
- [ ] 作者篩選正確（只顯示目標粉專的貼文）
- [ ] 分頁游標正常工作
- [ ] 首次基準建立（7 天 lookback）
- [ ] 通知管道發送成功（若已配置）
- [ ] 失敗重試機制運作
- [ ] 資料庫正確保存資料

### 除錯提示

#### 常見問題

1. **Graph API 401 錯誤**
   - 檢查 Access Token 是否有效
   - 確認 Token 具有必要權限

2. **無貼文返回**
   - 檢查粉專 ID 是否正確
   - 確認粉專有公開貼文

3. **通知發送失敗**
   - 檢查 Apprise URL 格式
   - 確認 LINE Token 有效

4. **資料庫錯誤**
   - 刪除 `monitor.sqlite3` 重新初始化
   - 檢查檔案權限

---

## 測試報告

執行測試後，請記錄以下資訊：

- Python 版本：`python --version`
- 測試結果：通過/失敗數量
- 線上驗證結果：成功/失敗項目
- 遇到的問題與解決方案

---

## 下一步

完成測試後：

1. 若測試通過，可以合併 PR 到 main 分支
2. 若測試失敗，請修復問題後重新測試
3. 考慮設定 CI/CD 自動測試
