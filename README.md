# 大便媒體控制的 Home Assistant 整合

[大便媒體控制 App](https://github.com/AiixiBear/media_control) 的 Home Assistant
自訂整合（Custom Integration）：把手機上正在播放的媒體變成 Home Assistant
裡的一個 `media_player` 實體，可以看歌名、演出者、專輯、封面和進度，也能
播放 / 暫停 / 上一首 / 下一首 / 跳轉播放位置。

## 需求

- 手機上的大便媒體控制 App（Android）
- 手機和 Home Assistant 在同一個區網
- 手機 App 已開啟「通知存取」權限（否則 App 看不到其他 App 在播什麼）
- App 1.1.0+ 才支援密碼保護；更舊的 App（沒有密碼功能）也可以繼續用

## 安裝

### HACS

1. 在 HACS → Integrations → 右上角選單 → Custom repositories，加入
   `https://github.com/AiixiBear/media_control_ha`，類別選 Integration。
2. 搜尋「大便媒體控制 HA 整合」並安裝。
3. 重新啟動 Home Assistant。

### 手動安裝

把 `custom_components/media_control_ha/` 整個資料夾複製到 Home Assistant
設定目錄下的 `custom_components/` 裡，然後重新啟動 Home Assistant。

## 設定

設定 → 裝置與服務 → 加入整合 → 搜尋「大便媒體控制」：

| 欄位 | 說明 |
| --- | --- |
| 位址 | 手機的區網 IP，例如 `192.168.0.2`（建議在路由器給手機固定 IP） |
| 埠號 | App 伺服器的連接埠，預設 `8080` |
| 密碼 | App「設定」頁面裡設的密碼；App 沒設密碼就留空 |
| 預設 packageName | 沒有正在播放的媒體時，指令要送去哪個 App（通常不用改） |

加入時整合會真的連一次手機驗證：位址 / 埠號錯誤會顯示「無法連線」，
密碼錯誤會顯示「密碼錯誤」。

### 選項

在整合的「設定」裡可以改輪詢間隔（預設 5 秒）和密碼。**在 App 改了密碼
之後，請在這裡同步更新**，否則實體會因為 401 驗證失敗而變成無法使用，
並跳出重新驗證的提示。

## 密碼與安全

- App 1.1.0+ 的「設定」頁面可以設定密碼（至少 8 個字元），整合會用
  `Authorization: Bearer <密碼>` 呼叫 App 的 API，密碼不會出現在網址裡。
- 密碼只存在 Home Assistant 的設定項目裡，不會寫進 log。
- App 沒設密碼時，整合不帶任何驗證標頭（和舊版行為一樣）。
- 這是區網內的 HTTP 服務，沒有 TLS 加密，請勿把手機的連接埠暴露到網際網路。

## 故障排除

| 現象 | 可能原因 |
| --- | --- |
| 設定時顯示「無法連線」 | 手機 IP / 埠號錯了、手機和 HA 不在同一個區網、App 沒開或伺服器沒在跑 |
| 設定時顯示「密碼錯誤」 | App 有設密碼但這裡沒填或填錯；去 App「設定」確認密碼 |
| 實體突然變成無法使用，並跳出重新驗證 | App 的密碼被改過了；跟著重新驗證流程輸入新密碼，或在整合選項裡更新 |
| 實體一直是 idle、沒有歌名 | 手機 App 沒有通知存取權限，或當下沒有 App 在播放；去手機系統設定開啟通知存取 |
| 指令沒反應 | 檢查手機 App 主畫面伺服器是否「正在跑」，以及播放中的 App 是否支援該操作 |
| 更新手機 App 後整合出錯 | 確認 App 版本和整合版本都是最新的；App 1.1.0+ 需要整合 1.1.0+ 才能用密碼功能 |

## 相容性

| 整合版本 | App 版本 | 備註 |
| --- | --- | --- |
| 1.1.0+ | 1.1.0+ | 密碼保護、`/api/auth/check` 驗證、重新驗證流程 |
| 1.1.0+ | 更舊 | 可以用，但沒有密碼功能（App 那邊本來就沒設密碼） |
| 1.0.x | 1.1.0+ | App 沒設密碼時可用；App 有設密碼時連不上，請升級整合 |

## 開發：測試

```sh
python -m venv .venv
.venv/bin/pip install -r tests/requirements_test.txt
.venv/bin/python -m pytest tests/ -v
```

`tests/test_api.py` 只需要 `aiohttp` 等小依賴就可以跑；`tests/test_config_flow.py`
需要 Home Assistant 測試環境（`pytest-homeassistant-custom-component`），
沒有裝的話會自動跳過。GitHub Actions 會在每次 push / PR 跑完整測試。
