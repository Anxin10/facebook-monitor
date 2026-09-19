# Facebook 監控：現成 repo 比較與混合實作

日期：2026-09-19。此報告依 GitHub metadata、下載的程式碼與官方文件整理；沒有真實 Meta Token 或通知接收設定，因此尚未完成線上驗證。

## 選擇

保留 `Anxin10/facebook-monitor` 的 Python + SQLite 架構，採用 Apprise 作為多管道通知依賴；參考 Meta tracking 專案的按粉專輪詢流程，以本專案需求重寫讀取器。未直接複製第三方來源碼。

| Repo | 實際用途 | 本次決定 | 授權 / 查詢時最後 push |
| --- | --- | --- | --- |
| [CSTVann/meta-tracking-alert2telegram](https://github.com/CSTVann/meta-tracking-alert2telegram) | 在指定貼文年齡範圍內，互動數低於門檻時發 Telegram 提醒，之後更新狀態；JSON 保存追蹤紀錄 | 參考逐粉專輪詢；不納入低互動篩選，避免漏掉一般新貼文 | MIT / 2026-06-03 |
| [caronc/apprise](https://github.com/caronc/apprise) | 統一通知 API，支援 Telegram、Email 等目的地 | 以套件依賴實際整合；每個目的地獨立 outbox 狀態 | BSD-2-Clause / 2026-09-17 |
| [kevinzg/facebook-scraper](https://github.com/kevinzg/facebook-scraper) | 非 Graph API 的公開粉專讀取工具 | 候選備援，未加入依賴；須先實测目標頁面和登入條件 | MIT / 2024-06-22 |
| [dgtlmoon/changedetection.io](https://github.com/dgtlmoon/changedetection.io) | 通用網頁變更偵測、瀏覽器步驟、通知 | 作為未來獨立網頁監控服務候選；不將整個系統混入輕量程式 | Apache-2.0 / 2026-09-18 |
| [VariabileAleatoria/Telegram-Facebook-Pages-Bot](https://github.com/VariabileAleatoria/Telegram-Facebook-Pages-Bot) | 從粉專清單傳送貼文至 Telegram | 保留比較，不匯入來源碼 | GPL-3.0 / 2022-12-01 |

最後 push 不是可用性保證。未找到可確認直接滿足「指定粉專每則限動監控」的可整合模組；不以一般貼文或網頁差異功能冒充限動支援。

## 修正原先摘要

- `git clone` 只建立本機副本，不會在 GitHub 建立 fork。
- 本次可透過未認證的 GitHub API 取得你的 repo 並 clone，無須再把它轉公開。
- `meta-tracking-alert2telegram` 並非通知所有新貼文；其核心有互動門檻與貼文年齡篩選。
- 「省時 70%」與「已有生產部署經驗」沒有經本次查核證實，不作為決策依據。

## 本次實際變更

1. 移除錯誤的 `sqlite3` pip 依賴及未使用的 facebook-sdk / Playwright 等必裝依賴。
2. 新增 Apprise 通知適配；LINE 使用 Messaging API push，不再呼叫 LINE Notify。
3. 每個 channel id 獨立追蹤送達與重試；成功目的地不因其他目的地失敗而重送。
4. 失敗通知回到 pending，依 30 秒起跳、最高 1 小時的退避間隔重試；保留舊 failed 紀錄的取回能力。
5. 貼文使用 `from.id` 判定作者，未知作者明確失敗；不當作空結果。
6. 分頁使用游標與固定 Graph host，不跟隨含 Token 的 next URL。
7. 分頁未完成或 API 錯誤時不保存部分資料，也不推進成功時間；空列表則為成功。
8. 新內容、通知佇列與基準在一個 SQLite transaction 內提交。
9. 首次監控範圍為最近 7 天，預設只建立基準；後續以上次成功檢查開始時間減 1 小時作為查詢下界。
10. 排程使用獨立 Scheduler，保留秒數精度；通知顯示時區採設定值而非主機時區。

## 運行方式

Python 3.10 以上，建議使用獨立虛擬環境：

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell 請改用 .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

建立 `.env`，不得提交真實憑證：

```dotenv
FACEBOOK_ACCESS_TOKEN=填入具有必要讀取資格的 Token
TELEGRAM_APPRISE_URL=tgram://BOT_TOKEN/CHAT_ID
EMAIL_APPRISE_URL=mailto://USER:PASSWORD@example.com
LINE_CHANNEL_ACCESS_TOKEN=填入 LINE 頻道存取權杖
LINE_TO=填入接收者 ID
```

Apprise 的 Email URL 僅為格式示意；依實際 SMTP 與收件者設定，特殊字元須 URL encode。每個 channel 設定一個目的地；同一 URL 不要塞多個接收者，才能維持目的地粒度的重試。

在 `config.yaml` 的 notifications 區塊，以實際需要的目的地取代 `channels: []`：

```yaml
notifications:
  timezone: Asia/Taipei
  notify_existing_on_first_run: false
  channels:
    - id: telegram_main
      backend: apprise
      url_env: TELEGRAM_APPRISE_URL
    - id: email_main
      backend: apprise
      url_env: EMAIL_APPRISE_URL
    - id: line_main
      backend: line
      token_env: LINE_CHANNEL_ACCESS_TOKEN
      recipient_env: LINE_TO
```

channel id 須保持穩定；移除目的地後，該目的地的待通知會保留但不再發送。重新加回同一 id 可繼續處理。新增目的地預設只接收之後發現的新內容，不補送既有內容。舊版 `channel: telegram/email/desktop` 可用對應 `*_APPRISE_URL` 遷移；舊的 SMTP 個別變數和 Telegram token/chat_id 變數不再由通知模組直接使用。

```bash
python main.py
```

預設等待第一個排程時間才讀取。只有 Graph API 資格、Token、粉專身份以及各通知目的地設定完成後，才可判定實際監控成功。第一次升級先備份既有 SQLite 檔案；既有已保存但未建立通知的資料不會自動重播。

## 已知限制

- 限時動態仍未實作，`stories.enabled` 必須維持 false。
- 不會自動繞過 Graph API 的權限限制；非管理粉專的公開內容仍需適當存取資格。
- 超過 max_pages 會標記 pagination_incomplete；需增加分頁上限或縮小首次 lookback 後再試。
- 重疊區間外才延遲出現的貼文仍可能漏掉；輪詢不是完整歷史封存。
- API 限流目前辨識並等待下一輪，尚無依 Retry-After 的跨轮動態退避。
- 通知重試間隔有上限，但次數尚未設上限；長期錯誤應處理憑證並檢視待通知。
- Telegram / Email 發送後若成功回應遺失，仍可能重複；LINE retry key 也受平台有效期限約束。
- 單一進程運行，未實作多 worker 的 notification claim。不要同時啟動兩個實例共用同一 DB。
- 尚未實作異常外部通知與資料保留清理；現階段以 DB 狀態及日誌觀察。
- requirements 是相容範圍，不是供應鏈鎖定檔；正式部署應固定已驗證版本。

## 查核基準與來源

- 原專案 commit：`e860036d31b3fba2885dbfb4520ef59dc4c16f92`
- 參考 Meta tracking commit：`6c4f6ec6df5567f26d4508962da66846bff4bd73`
- [Apprise Python API](https://github.com/caronc/apprise#api)
- [LINE Messaging API](https://developers.line.biz/en/reference/messaging-api/)
- [LINE 重試機制](https://developers.line.biz/en/docs/messaging-api/retrying-api-request/)

Apprise 由 pip 安裝並附帶其套件授權。上述其他 repo 僅供比較或設計參考，未複製其程式碼，因此未將不同授權的來源碼混入本專案。未替你的整個 repo 擅自選定開源授權。

## 驗證結果

在 Python 3.12 虛擬環境安裝依賴成功；10 項離線測試全部通過，涵蓋三頁游標、作者篩選、空基準、部分失敗、分頁上限、交易回滾、重啟去重、逐目的地重試、Apprise 呼叫與 LINE 重試回應。所有通知傳送在測試中模擬，未向任何接收者發送訊息。未執行需要真實憑證的線上驗證。
