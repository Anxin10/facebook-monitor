# Facebook 指定粉專監控系統

輕量化的 Facebook 粉專貼文與限時動態監控工具。

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
└── src/
    ├── __init__.py
    ├── config.py        # 設定載入
    ├── database.py      # SQLite 資料層
    ├── scheduler.py     # 排程器
    ├── post_fetcher.py  # 貼文讀取器
    ├── story_fetcher.py # 限動讀取器
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

### 3. 配置監控目標

編輯 `config.yaml` 設定要監控的粉專與通知管道。

### 4. 啟動監控

```bash
python main.py
```

## 設計文件

詳細設計規格請參閱 [`facebook-monitor-design.md`](facebook-monitor-design.md)

## 注意事項

- 首次執行會建立基準，不會通知既有內容
- 需要有效的 Meta App 與 Page Access Token
- 限時動態功能需先驗證資料來源後才啟用
- Token 與敏感資訊請存放於 `.env`，勿提交至 Git

## 授權

MIT License
