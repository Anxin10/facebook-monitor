# Facebook 指定粉專監控系統

輕量化的 Facebook 粉專貼文與限時動態監控工具。

> ⚠️ **注意**：此專案為個人學習與實驗用途，不保證功能完整性與穩定性。

## 功能特性

- 監控指定 Facebook 粉專的公開貼文
- 限時動態監控（待驗證啟用）
- 低資源、低維護成本架構
- SQLite 本地資料儲存
- 可擴展的通知管道（LINE、Telegram、Email 等）

## 專案結構

```
facebook-monitor/
├── README.md
├── requirements.txt
├── config.yaml          # 設定檔範例
├── .env.example         # 環境變數範例
├── .gitignore
├── main.py              # 主程式入口
├── facebook-monitor-design.md  # 設計規格文件
├── NEXT_STEPS.md        # 下一步優先順序
├── scripts/             # 驗證腳本
│   ├── README.md
│   ├── validate_api.py
│   ├── test_post_fetcher.py
│   ├── validate_database.py
│   └── run_all_validations.py
└── src/
    ├── __init__.py
    ├── config.py        # 設定載入
    ├── database.py      # SQLite 資料層
    ├── scheduler.py     # 排程器
    ├── post_fetcher.py  # 貼文讀取器
    ├── story_fetcher.py # 限動讀取器（待驗證）
    ├── notifier.py      # 通知發送器
    └── utils.py         # 公用工具
```

## 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 設定環境變數

複製 `.env.example` 為 `.env` 並填寫必要資訊：

```bash
cp .env.example .env
```

必要環境變數：
- `FACEBOOK_APP_ID`
- `FACEBOOK_PAGE_ACCESS_TOKEN`

### 3. 配置監控目標

編輯 `config.yaml` 設定要監控的粉專與通知管道。

### 4. 執行驗證腳本（推薦）

**資料庫驗證（無需 Token）：**
```bash
python scripts/validate_database.py
```

**API 驗證（需要 Token）：**
```bash
python scripts/validate_api.py
```

### 5. 啟動監控

```bash
python main.py
```

## 下一步優先順序

詳細的開發與驗證優先順序請參閱 [`NEXT_STEPS.md`](NEXT_STEPS.md)

## 設計文件

詳細設計規格請參閱 [`facebook-monitor-design.md`](facebook-monitor-design.md)

## 驗證腳本說明

請參閱 [`scripts/README.md`](scripts/README.md)

## 注意事項

- 首次執行會建立基準，不會通知既有內容
- 需要有效的 Meta App 與 Page Access Token
- 限時動態功能需先驗證資料來源後才啟用
- Token 與敏感資訊請存放於 `.env`，勿提交至 Git
- 請遵守 Facebook Platform 政策與使用條款

## 授權

MIT License