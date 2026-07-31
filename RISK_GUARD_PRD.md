# RISK_GUARD_PRD.md — 台股風控儀表板 Handoff Spec

> 交付對象:Claude Code(實作)
> 擁有者:Qui
> 日期:2026-07-31
> 版本:v1.1

**v1.1 變更(2026/7/23–7/31 實戰週期後更新):**
1. 新增「介面三:MCP tools」——Risk Guard 狀態掛上現有 Alphatecx v2 MCP server,dashboard / Telegram / Claude 對話三方共用同一份即時狀態
2. 實作目標釘死:寫進現有 `alphatecx` codebase(alphatecx-v2),不開新 server;`rg_` 前綴隔離
3. M2 新增「交割款檢查」子模組(7/24 實際發生差點違約交割案例)
4. M1 回放驗收案例擴充至完整 7 月風暴(7/16–7/31)
5. 新增第 10 節「實戰校準案例」——本週期真實交易作為迴歸測試
6. 種子資料更新:目前空手 100% 現金,持倉表改灌觀察名單

---

## 0. 一句話定位

**Risk Guard 是一個「阻止使用者虧大錢」的收盤後風控系統 + 盤中保命警報,不是選股機、不是預測機。**

判斷任何功能該不該做的唯一標準:

> 這個功能是在「阻止虧錢」還是在「慫恿買進」?前者做,後者不做。

---

## 1. 背景與痛點(Why)——已全數實戰驗證

使用者是波段操作的台股散戶,已有自建 Alphatecx / Alpha v2 MCP 資料層。2026/7 修正期(八個交易日 -16%)完整驗證了每個痛點:

| 痛點 | 實例(全部真實發生) | 對應模組 |
|---|---|---|
| 大盤系統性崩跌沒預警 | 7/17 -6.47%、7/28 -4.65%、7/29 -3.76% | M1 風險燈號 |
| 停損不執行 / 凹單 | 宏碁 28.6 出場線,掙扎 4 天才執行(29.05 出,-3.8%) | M2 停損警報 |
| 追高買在垂直段頂端 | 3231 緯創買在 4 天 +25% 後的 175(隨後 -12%) | M2 checklist + M1 |
| 交割款不足差點違約 | 7/24 帳戶缺 26,211,券商 14:02 才簡訊通知 | M2 交割款檢查 |
| 買錯族群 / 買錯供應鏈方向 | 記憶體漲價:賣方(華邦電)噴、買方(廣達 ODM)弱 | M3 族群強度 |
| 天地板 / 開高走低 | 7/24 緯創開 180 → 殺 171(-4.5% 反轉) | M4 盤中異常 |
| 誤觸處置股 / 飆股明牌詐騙 | 詐騙帳號名單股 3 日 -21%~-55% | M6 公告輪詢 |

**明確的非目標(Non-goals):**
- ❌ 不產生任何「買進」訊號或推薦
- ❌ 不做盤中搶單 / 高頻策略(散戶搶不過量化自營)
- ❌ 不做全市場掃描(既有 flow_leaders_scan / scan_limit_board 職責)
- ❌ 金口訣/玄學層**不進訊號計算**,只有「否決今日執行」的權力(M7)

---

## 2. 實作目標與既有資產(Reuse, don't rebuild)

**實作位置(v1.1 釘死):**
- 寫進現有 `alphatecx` repo(alphatecx-v2-mcp 部署),**不開新 MCP server**
- 程式碼放獨立資料夾 `/riskguard`,邏輯獨立、部署合併
- 所有新 DB 表 `rg_` 前綴,所有新 MCP tools `rg_` 前綴
- cron 加在同一個 Vercel 專案;**唯一分開跑的是 M4 盤中 worker**(常駐程序,自行決定 fly.io / GitHub Actions / 本機,寫回同一顆 Postgres,盤中掛掉不影響收盤風控)

| 既有資產 | 用途 |
|---|---|
| Alphatecx MCP | twse_daily_close/history、twse_inst_flow、twse_margin_balance、twse_foreign_holdings、monthly_revenue、yf_* |
| Alpha v2 MCP | quote(即時報價+漲跌停價)、session_state(交易日/盤別/颱風假)、q_index_history(大盤與類股指數)、sc_sector_momentum、raw_flow_history、d_recent(既有 cron 簡報管線) |
| Fugle API key | M4 盤中 WS 行情 |
| Vercel + Postgres | cron、DB 直接加表 |

**新增外部資料源(全部免費公開):**

| 資料 | 來源 | 更新時間 | 模組 |
|---|---|---|---|
| 三大法人期貨留倉 | TAIFEX 每日 CSV | ~15:00 | M1 |
| 上市漲跌家數 | TWSE MI_INDEX 彙總(或 OpenAPI) | 收盤後 | M1 |
| 全市場融資餘額 | TWSE MI_MARGN 彙總 | 收盤後 | M1 |
| 借券賣出餘額 | TWSE OpenAPI(TWT93U) | ~21:00 | M5 |
| MOPS 重大訊息 | MOPS t05sr01_1 當日重訊 | 全日不定時 | M6 |
| 注意股/處置股 | TWSE/TPEx 公告 | 收盤後~晚間 | M6 |

---

## 3. 系統架構

```
┌────────────────────────────────────────────────────┐
│  Vercel Cron(同一專案)                            │
│  ├ 15:30  post_close_pipeline                      │
│  │   ├ M1 risk_light 計算                          │
│  │   ├ M2 stop_check(官方收盤價)                 │
│  │   ├ M2b settlement_check(交割款 vs 餘額)      │
│  │   ├ M3 sector_strength                          │
│  │   └ 快照落 DB(held_pct、margin、breadth)      │
│  ├ 21:30  evening_pipeline                         │
│  │   ├ M5 借券餘額(後期)                         │
│  │   └ M6 注意/處置股比對                          │
│  ├ 08:30  pre_market_pipeline(燈號+持倉風險摘要) │
│  └ [獨立 worker] 09:00–13:30                       │
│      ├ M4 anomaly_watch(僅持倉+自選)             │
│      └ M6 MOPS 重訊輪詢(每 10 分)                │
├────────────────────────────────────────────────────┤
│  Postgres(既有 instance,rg_ 表)                 │
├────────────────────────────────────────────────────┤
│  介面一:Telegram Bot(推播+指令)                 │
│  介面二:/status Dashboard(可選,v2)             │
│  介面三:MCP tools(rg_*,掛現有 server)★v1.1    │
└────────────────────────────────────────────────────┘
```

---

## 4. DB Schema(新增表)

```sql
-- 持倉與自選(M2/M4 監控清單)
CREATE TABLE rg_positions (
  id            SERIAL PRIMARY KEY,
  ticker_id     TEXT NOT NULL,
  name          TEXT,
  kind          TEXT NOT NULL DEFAULT 'position',  -- position | watch
  cost          NUMERIC,
  qty_lots      NUMERIC,
  warn_price    NUMERIC,            -- 警戒線(減半)
  exit_price    NUMERIC,            -- 出場線(全出)
  hard_stop_pct NUMERIC DEFAULT 10,
  note          TEXT,
  active        BOOLEAN DEFAULT TRUE,
  created_at    TIMESTAMPTZ DEFAULT now()
);

-- 每日市場快照(M1)
CREATE TABLE rg_market_daily (
  date              DATE PRIMARY KEY,
  taiex_close       NUMERIC,
  taiex_pct         NUMERIC,
  taiex_ma20        NUMERIC,
  taiex_ma60        NUMERIC,
  adv_count         INT,
  dec_count         INT,
  margin_balance    NUMERIC,
  margin_chg_5d_pct NUMERIC,
  fut_foreign_net_oi INT,
  risk_light        TEXT,     -- green | yellow | red
  risk_score        INT,
  reasons           JSONB
);

-- 警報事件流(所有推播先寫這裡再發)
CREATE TABLE rg_alerts (
  id         SERIAL PRIMARY KEY,
  ts         TIMESTAMPTZ DEFAULT now(),
  kind       TEXT,   -- risk_light_change | stop_warn | stop_exit | settlement_gap |
                     -- anomaly_limit_open | anomaly_crash | anomaly_volume |
                     -- news_mops | disposition | sector_exit
  ticker_id  TEXT,
  severity   TEXT,   -- info | warn | critical
  payload    JSONB,
  pushed     BOOLEAN DEFAULT FALSE
);

-- 外資持股每日快照(M5 趨勢,Phase 1 就開始存)
CREATE TABLE rg_foreign_holdings_daily (
  date DATE, ticker_id TEXT, held_pct NUMERIC,
  PRIMARY KEY (date, ticker_id)
);

-- 族群強度每日(M3)
CREATE TABLE rg_sector_daily (
  date DATE, sector_id TEXT, rs_20d NUMERIC, inst_net_5d NUMERIC, rank INT,
  PRIMARY KEY (date, sector_id)
);

-- 交割款排程(M2b)
CREATE TABLE rg_settlements (
  date DATE PRIMARY KEY,
  net_amount NUMERIC,        -- 正=入帳 負=應付
  note TEXT
);

-- 決策日誌(rg_journal_add 寫入)
CREATE TABLE rg_journal (
  id SERIAL PRIMARY KEY,
  ts TIMESTAMPTZ DEFAULT now(),
  text TEXT NOT NULL,
  ticker_id TEXT
);

-- 節律層(M7)
CREATE TABLE rg_no_trade_days (
  date DATE PRIMARY KEY,
  reason TEXT
);
```

**種子資料(v1.1 更新——目前空手,灌觀察名單):**

```sql
INSERT INTO rg_positions (ticker_id,name,kind,note) VALUES
 ('2344','華邦電','watch','記憶體主攻候選。進場三開關:大盤連2日站穩 + 回踩不破 + 外資連買。回踩參考區收盤後更新'),
 ('2324','仁寶','watch','副線。復活條件:收復34箱底 + 外資回買 + 相對大盤不轉弱(記憶體漲價=其成本,標準加嚴)'),
 ('8299','群聯','watch','NAND控制晶片,次選'),
 ('2408','南亞科','watch','族群風向指標,資金不足整張,僅觀察');
-- 拉黑名單(僅記錄於 note,禁止買進提示):國巨2327、光罩2338、力成6239(<320)、聯電2303(<130)、精材3374
```

---

## 5. 模組規格

### M1 市場風險燈號(Phase 1)🟢🟡🔴

每日 15:30 計算,五子項計分:

| # | 指標 | 資料源 | 計分 |
|---|---|---|---|
| 1 | TAIEX vs MA20/MA60 | q_index_history | 收盤<MA20:+1;<MA60:再+2 |
| 2 | 漲跌家數 | MI_INDEX | 5日均 adv/(adv+dec) <0.40:+2;<0.45:+1 |
| 3 | 融資 | MI_MARGN | 5日增速>+3% 且 TAIEX 5日報酬<0:+2 |
| 4 | 外資期貨淨留倉 | TAIFEX | 淨空>20,000口:+2;>10,000口:+1 |
| 5 | 單日殺盤 | q_index_history | ≤-2%:+1;≤-3.5%:+2 |

| score | 燈 | 行為 |
|---|---|---|
| 0–2 | 🟢 | 正常 |
| 3–4 | 🟡 | 新倉減半、停損上移 |
| ≥5 | 🔴 | 禁新倉、建議總持股≤50%;發 no_new_entries 旗標(當沖系統將來吃這個) |

規則:燈號**變化**才推播;red 期間每天 pre_market 重申;reasons 存明細(可解釋);閾值放 config,改動記 CHANGELOG。
**綠燈解鎖條件(v1.1 補):**紅轉黃需「不再新增子項扣分 + 指數連 2 日不破前低」;黃轉綠需「站回 MA20 或連 3 日收高」。單日暴漲(如 7/31 +8%)只算「候選第一天」,不直接轉燈。

### M2 持倉停損警報 + 進場 Checklist(Phase 1)

**停損警報:**
- 15:35 用官方收盤價檢查:close ≤ warn → 減半推播;close ≤ exit → 全出推播(訊息必含「明天開盤執行」動詞句)
- 未設線用 cost×(1−hard_stop_pct/100) 兜底;觸發後標記不重複轟炸
- **執行建議文案(v1.1 實戰教訓):**stop_exit 推播固定附一句「建議改掛券商觸價條件單(觸價=出場線下一檔、市價、長效),把執行交給機器」——28.6 案例證明收盤規則+人手,會拖 4 天

**M2b 交割款檢查(v1.1 新增):**
- 使用者以 bot 指令回報成交(`/trade buy 2344 51.5 x3`)→ 系統寫 rg_settlements(T+2 規則,跨週末順延)
- 15:30 檢查:未來 3 日淨應付 vs 使用者回報的交割戶餘額(`/balance 476276` 手動更新)→ 缺口 → critical 推播,**提前 2 天**,不讓券商 14:02 簡訊當第一通知
- 規則寫進 checklist:單筆買進 ≤ 可用現金 70%

**進場 Checklist(`/check <ticker>` 與 rg_checklist 共用):**
1. 市場燈號 🟢?
2. 族群排名前5?(M3 上線前跳過)
3. 5日漲幅 <15%?(垂直段擋刀——175 案例)
4. 非注意/處置股?
5. 今日為可執行日?(M7)
6. **(v1.1 新增)買進金額 ≤ 可用現金 70%?**

任一 ❌ →「今天不買。原因:…」。措辭只有「沒有阻止你的理由」,永無「建議買進」。

### M3 族群強度榜(Phase 2)

- 官方類股指數 + 自訂題材族群表(初版沿用 sc_supply_chain_map pillar)
- rs_20d = 族群20日報酬 − TAIEX;加計成分股5日法人合計買超;每日排名
- **供應鏈方向標記(v1.1 新增,DELL/記憶體案例):**題材族群表加 `side` 欄(beneficiary | cost_bearer)。範例:記憶體漲價 → 華邦電/南亞科=beneficiary,廣達/緯創/仁寶/宏碁=cost_bearer。checklist 第2題對 cost_bearer 降評
- 持倉股族群跌出前10 → sector_exit 推播

### M4 盤中異常監控(Phase 2.5)

僅監控 rg_positions(position+watch)。Fugle WS 一分K主、quote 60秒輪詢備援。開盤前快取當日漲跌停價。

| 規則 | 條件 | 級別 |
|---|---|---|
| 漲停打開回落 | 曾觸漲停(或距<0.5%)後自高點回落>4% | critical |
| 高點急殺 | 自當日高點回落>7% | critical |
| 爆量下殺 | 5分量>20日同時段均量×5 且 5分跌>2% | warn |
| 盤中觸線 | 成交價≤exit_price | critical |

每檔每種一日最多2次、間隔≥15分;09:00–09:03 靜音;試撮不觸發(session_state.price_is_indicative);WS斷線降級+通知。

### M5 外資動機評分(Phase 3)

held_pct 快照 Phase 1 就開始存。評分(−9~+9):held_pct 20日斜率 ±2、借券10日方向 ±2、逆勢買(跌日買超≥3/10日)+2、buy_day_ratio(10日)≥0.7/+2 ≤0.3/−2、期貨同向 ±1。≥+4 真吸貨;≤−3 出貨疑慮。掛 `rg_intent_score(ticker)`。教訓:連續性 > z-score;投信方向必須並列註記。

### M6 新聞/公告輪詢(Phase 4)

- 注意/處置股:21:30 比對監控清單 → 命中 critical(處置=分盤交易)
- MOPS 重訊:盤中每10分,只比對監控清單,黑名單關鍵字(調查|搜索|違約|跳票|重編|處分.*廠房|災|停工|董事長.*辭)→ warn+連結。純關鍵字,誤報可接受
- 媒體 RSS:v2

### M7 節律層(金口訣否決權)(Phase 4)

`/notrade <date> <reason>` → checklist 第5題 ❌ + pre_market 註記。**不得出現在任何評分/燈號/警報計算中**,只有否決權——code review 驗收條件。

---

## 6. 介面

### 介面一:Telegram Bot

```
/status            今日燈號 + 持倉風險總覽
/check <ticker>    進場 checklist(6題)
/pos               持倉與線位
/setpos 2344 cost=51.5 warn=49 exit=47.8
/watch <ticker>    加自選
/trade buy|sell <ticker> <price> x<lots>   回報成交(餵 M2b)
/balance <amount>  更新交割戶餘額
/notrade <date> <reason>
```

推播格式:`[燈號emoji] [嚴重度] 股名(代碼)|事實一行|要做的動作一行|兵法一句`。每則必含動作句。先寫 rg_alerts 再發,補發 critical。

**兵法文案層(教義層,零計算邏輯,存 config 查表):**

| 事件 kind | 引句 |
|---|---|
| risk_light_change → red | 不可勝者,守也 |
| risk_light_change → green(無標的) | 善戰者,無智名,無勇功 |
| stop_warn / stop_exit | 小敵之堅,大敵之擒也 |
| anomaly_limit_open / anomaly_crash | 兵貴勝,不貴久 |
| checklist 攔截 | 勝兵先勝而後求戰 |
| sector_exit | 避實而擊虛 |

約束:與 M7 相同——不得進入任何評分或觸發計算,僅為訊息文案。

### 介面二:/status Dashboard(可選,v2)
單頁:燈號+五子項、持倉表、族群前十、近期警報。不做圖表堆砌。

### 介面三:MCP tools(v1.1 新增,Phase 1 就做)

掛在現有 alphatecx-v2 MCP server,沿用現有 tool 註冊方式,`rg_` 前綴:

| tool | 回傳 |
|---|---|
| `rg_status()` | 今日燈號、score、五子項明細、大盤關鍵位、交割款狀態 |
| `rg_positions()` | 持倉/自選、成本、warn/exit 線、現價距離、觸發狀態 |
| `rg_alerts(days=3)` | 近期警報流水(kind、severity、payload) |
| `rg_checklist(ticker)` | 6 題即時判定 + 總結論 |
| `rg_journal_add(text, ticker?)` | 寫入決策日誌,回傳 id |

目的:dashboard、Telegram、Claude 對話三方共用同一份即時狀態;對話中做的決定用 rg_journal_add 落地,之後推播可引用使用者自己的決定。全部為 DB 薄讀取層(journal_add 除外),無副作用。

---

## 7. 實作順序與驗收

| Phase | 內容 | 工時估 | 驗收 |
|---|---|---|---|
| 1 | DB schema + M1 + M2 + M2b + Telegram bot + MCP tools(rg_status/positions/alerts/checklist/journal_add)+ held_pct 快照 | 一個週末 | 見下方回放驗收;模擬觸線推播含動作句;連3交易日 cron 無失敗;Claude 對話可呼叫 rg_status 取得當日燈號 |
| 2 | M3 族群強度 + checklist 全6題 | 2–3 晚 | 垂直段情境回「今天不買」 |
| 2.5 | M4 盤中異常 | 1 週 | 7/24 緯創一分K回放:11:00 後自 179.5 回落觸發≤1次 |
| 3 | M5 動機評分 + 借券 | 2–3 晚 | 3231 在 7/23 資料下 ≥+4;2353 在 7/28 資料下轉負向 |
| 4 | M6 公告 + M7 節律 | 2 晚 | 處置股命中;/notrade 後第5題 ❌ |

**M1 回放驗收(v1.1 擴充——用 2026/6/1–7/31 完整風暴校準):**
| 日期 | 實際 | 必須輸出 |
|---|---|---|
| 7/07 | −2.31% 破月線 | ≥yellow |
| 7/16 | −6.47% 前一日 | yellow 或 red |
| 7/17 | −6.47% | red |
| 7/24 | −2.67% | red |
| 7/28 | −4.65% | red |
| 7/29 | −3.76% | red |
| 7/30 | −0.26% 止穩 | red 維持(不得單日轉綠) |
| 7/31 | +8.0% | red→最多 yellow 候選(不得直接 green) |
| 6/08 | −3.48% 急崩型 | 已知抓不到,列為停損兜底案例,寫進 README 限制說明 |

**通用工程要求:**單源失敗不炸 pipeline、缺料照算並註記 data_missing;全部 Asia/Taipei;交易日走 session_state;閾值進 config;假日 early-return。

---

## 8. 明確不做清單

1. 任何買進推薦、目標價、預測
2. 全市場即時掃描
3. 券商下單 API(人是最後閘門;條件單掛在券商端)
4. 新聞 NLP(v1 關鍵字)
5. 盤中大單 cumulative delta(Risk Guard 穩定運行一個月後評估)
6. 金口訣進任何計算

---

## 9. 成功指標(上線一個月回顧)

- 紅/黃燈日 vs 綠燈日的大盤報酬差
- 停損警報發出後的實際執行率(基準:2026-07-31 首次完整執行,29.05 出場)
- /check 攔下筆數與被攔標的其後 10 日報酬
- 天地板/急殺警報首響時間 vs 當日高點回落幅度
- 交割款警報是否早於券商簡訊 ≥1 天

---

## 10. 實戰校準案例(2026/7 風暴週期——寫成迴歸測試)

| # | 案例 | 事實 | 系統應有行為 |
|---|---|---|---|
| 1 | 垂直段追高 | 7/23 緯創 175 買進,5日漲幅+25.9% | checklist Q3 ❌ 攔截 |
| 2 | 天地板前奏 | 7/24 緯創開180→殺171,自高點-4.7% | M4 anomaly_crash 觸發 |
| 3 | 交割缺口 | 7/24 應付472,487 vs 餘額446,276 | M2b 提前2天 critical |
| 4 | 停損拖延 | 宏碁 28.6 線,7/28–7/31 掙扎4天 | stop_exit 推播含條件單建議句 |
| 5 | 外資翻臉 | 宏碁 7/28 外資 -9,871張(吸貨劇本破) | M5 intent 轉負 + 註記 |
| 6 | 供應鏈兩面 | 記憶體漲價:SNDK+22%,DELL/廣達承壓 | M3 side 欄:beneficiary vs cost_bearer |
| 7 | 假V轉 | 7/27 盤中-500拉回平盤,7/28 -4.65% | 燈號不因單日下影線降級 |
| 8 | 暴漲不轉綠 | 7/31 +8% | red→yellow 候選,禁止當日 green |
| 9 | 拉黑名單 | 國巨-55%、光罩、力成285、聯電 | watch note 含拉黑,checklist 提示 |
| 10 | 明牌詐騙模式 | 假帳號「進場價=收盤價+5%」名單 | 不在系統範圍,寫進 README 使用者教育段 |
