# v0.2 - Real-world validation ready

## 里程碑目標

完成核心程式碼正確性修正，準備真實環境驗證。

## 核心修正清單

### ✓ Graph API 端點
- [x] 使用 `/{page_id}/posts` 而非 `/feed`
  - 直接取得粉專發布的貼文
  - 不需要額外作者篩選
  - 減少 API 呼叫與資料處理

### ✓ Cursor Pagination
- [x] 真實 cursor pagination 支援
  - 使用 `paging.cursors.after`
  - 不跟隨含 Token 的 next URL
  - 固定 Graph host 與 API version

### ✓ Transaction Integrity
- [x] Incomplete fetch = no commit
  - API 錯誤時不保存部分資料
  - 批次保存使用 SQLite transaction
  - 確保資料一致性

### ✓ First-run Baseline
- [x] 首次基準不 spam
  - `notify_existing_on_first_run` 控制
  - 預設 false，只建立基準不通知
  - 基準建立後才開始通知新貼文

### ✓ API Version & Token
- [x] 可配置 API version（預設 v26.0）
- [x] 統一 GraphClient token 處理
- [x] 支援 `Retry-After` 限流辨識

### ✓ LINE Retry
- [x] 冪等重試機制
  - 正確處理 `is_duplicate` 回應
  - 保存 `retry_key` 用於追蹤
  - 避免重複通知

### ✓ Scheduler Precision
- [x] 秒數精度排程
  - 支援小於 60 秒的間隔
  - 正確使用 `schedule.every().seconds`

## 測試覆蓋

### 回歸測試
- [x] 資料庫測試（12 項）
- [x] 貼文讀取器測試（11 項）
- [x] 通知模組測試（7 項）
- [x] GraphClient 測試（7 項）

### CI/CD
- [x] GitHub Actions 自動測試
- [x] 多 Python 版本支援（3.10, 3.11, 3.12）
- [x] 測試覆蓋率報告

## 驗證腳本

### scripts/validate_api.py
- [x] 與 PostFetcher 共用 GraphClient
- [x] 測試 `/{page_id}` 端點
- [x] 測試 `/{page_id}/posts` 端點
- [x] 測試 cursor pagination
- [x] 測試限流處理

## 使用方式

### 環境變數
```bash
FACEBOOK_ACCESS_TOKEN=你的 Token
TARGET_PAGE_ID=100054441671873  # 可選
```

### 執行驗證
```bash
python scripts/validate_api.py
```

### 執行測試
```bash
python run_tests.py
```

### 運行監控
```bash
python main.py
```

## 已知限制

- [ ] 限時動態仍未實作
- [ ] 單一進程運行
- [ ] 未實作 Page Webhooks（仍為 polling）

## 下一步

1. **Live Validation** - 使用真實 Page Access Token 驗證
2. **Single Channel E2E** - 單一通知管道 end-to-end 測試
3. **Production Deployment** - 部署到生產環境
4. **Webhooks Evaluation** - 評估 Page Webhooks 可行性

## 相關文件

- [HYBRID_INTEGRATION.md](HYBRID_INTEGRATION.md) - 原始技術決策
- [TESTING.md](TESTING.md) - 測試與驗證指南
- [README.md](README.md) - 專案說明

---

**狀態**: Core correctness fixes completed, ready for live validation
**Branch**: `fix/core-correctness`
**Target**: Merge to `main` after validation
