# 驗證腳本說明

此目錄包含 Facebook 監控系統的驗證腳本。

## 腳本列表

### 1. validate_api.py
驗證 Facebook API 存取能力

**功能：**
- 檢查環境變數設定
- 驗證 Access Token 有效性
- 驗證目標粉專 ID
- 測試貼文 Feed 讀取
- 測試作者篩選邏輯

**使用方式：**
```bash
python scripts/validate_api.py
```

**環境變數要求：**
- `FACEBOOK_APP_ID`
- `FACEBOOK_PAGE_ACCESS_TOKEN`
- `FACEBOOK_USER_ACCESS_TOKEN` (可選)

---

### 2. test_post_fetcher.py
測試貼文讀取與去重邏輯

**功能：**
- 實際讀取粉專貼文
- 測試分頁處理
- 測試作者篩選
- 模擬重複檢查場景

**使用方式：**
```bash
python scripts/test_post_fetcher.py
```

**環境變數要求：**
- `FACEBOOK_PAGE_ACCESS_TOKEN`

---

### 3. validate_database.py
測試 SQLite 資料庫模組

**功能：**
- 測試資料庫初始化
- 測試目標 CRUD 操作
- 測試內容項目操作（含去重）
- 測試檢查狀態記錄
- 測試通知管理

**使用方式：**
```bash
python scripts/validate_database.py
```

**無需環境變數**

---

### 4. run_all_validations.py
完整整合測試

**功能：**
- 檢查必要套件
- 檢查環境變數
- 依序執行各驗證腳本

**使用方式：**
```bash
python scripts/run_all_validations.py
```

---

## 建議執行順序

1. **安裝依賴**
   ```bash
   pip install -r requirements.txt
   ```

2. **設定環境變數**
   ```bash
   cp .env.example .env
   # 編輯 .env 並填寫必要資訊
   ```

3. **資料庫驗證**（無需 API Token）
   ```bash
   python scripts/validate_database.py
   ```

4. **API 驗證**（需要 Token）
   ```bash
   python scripts/validate_api.py
   ```

5. **貼文讀取測試**（需要 Token）
   ```bash
   python scripts/test_post_fetcher.py
   ```

---

## 常見問題

### Q: Token 驗證失敗
A: 請確認：
1. Token 是否過期
2. Token 是否有 Page Public Content Access 權限
3. 目標粉專是否為公開粉專

### Q: 無法讀取貼文
A: 請確認：
1. Token 權限足夠
2. 目標粉專 ID 正確
3. 粉專內容為公開可見

### Q: 資料庫測試失敗
A: 請確認：
1. 執行目錄有寫入權限
2. Python 版本支援（建議 3.8+）
3. src/database.py 檔案存在
