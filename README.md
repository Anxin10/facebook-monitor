# Facebook 監控系統

Python 實作的 Facebook 粉絲專頁貼文監控工具，使用官方 Graph API 讀取貼文，支援多管道通知。

## 功能特性

- **貼文監控**: 使用 Facebook Graph API 讀取指定粉專的貼文
- **多管道通知**: 支援 Telegram、Email、LINE 等多種通知方式
- **SQLite 儲存**: 輕量級資料庫，無需額外服務
- **智能排程**: 可自訂檢查間隔，支援秒數精度
- **重試機制**: 通知失敗自動重試，指數退避
- **完整測試**: 30+ 項離線測試確保程式碼正確性

## 快速開始

### 環境要求

- Python 3.10 以上
- Facebook Page Access Token（具有讀取粉專貼文資格）

### 安裝

```bash
# 建立虛擬環境
python -m venv .venv

# 啟動虛擬環境
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1

# 安裝依賴
python -m pip install -r requirements.txt
```

### 配置

1. 複製 `.env.example` 為 `.env` 並填入憑證：

```bash
cp .env.example .env
```

2. 編輯 `.env` 填入實際值：

```dotenv
FACEBOOK_ACCESS_TOKEN=你的 Facebook Access Token
TELEGRAM_APPRISE_URL=tgram://BOT_TOKEN/CHAT_ID
LINE_CHANNEL_ACCESS_TOKEN=你的 LINE Channel Token
LINE_TO=接收者 User ID
```

3. 編輯 `config.yaml` 設定監控目標與通知管道：

```yaml
targets:
  - page_id: "你的粉專 ID"
    url: "https://www.facebook.com/你的粉專"
    enabled: true

notifications:
  timezone: Asia/Taipei
  channels:
    - id: telegram_main
      backend: apprise
      url_env: TELEGRAM_APPRISE_URL
```

### 運行

```bash
python main.py
```

## 測試

### 執行離線測試

```bash
# 使用測試運行腳本
python run_tests.py

# 或使用 unittest
python -m unittest discover -s tests -v
```

### 測試涵蓋

- **資料庫測試**（12 項）: 資料儲存、去重、分頁、通知管理
- **貼文讀取器測試**（11 項）: API 呼叫、作者篩選、錯誤處理
- **通知模組測試**（7 項）: Apprise、LINE、重試機制

詳細測試指南請參閱 [TESTING.md](TESTING.md)

## 技術架構

詳細技術決策與實作說明請參閱 [HYBRID_INTEGRATION.md](HYBRID_INTEGRATION.md)

### 核心模組

- `src/post_fetcher.py`: Facebook Graph API 貼文讀取
- `src/notifier.py`: 多管道通知發送（Apprise + LINE API）
- `src/database.py`: SQLite 資料儲存與交易管理
- `src/scheduler.py`: 排程器
- `src/config.py`: 設定管理

### 測試模組

- `tests/test_database.py`: 資料庫測試
- `tests/test_post_fetcher.py`: 貼文讀取器測試
- `tests/test_notifier.py`: 通知模組測試

## 已知限制

- 限時動態功能尚未實作
- 單一進程運行，不支援多實例並行
- 需自行處理 Facebook API 權限與限流

## 文件

- [HYBRID_INTEGRATION.md](HYBRID_INTEGRATION.md) - 技術決策與實作說明
- [TESTING.md](TESTING.md) - 測試與驗證指南
- [config.yaml](config.yaml) - 設定檔範例

## 授權

專案授權尚未正式選定，請參閱專案根目錄。

## 貢獻

歡迎提出 Issue 或 Pull Request。
