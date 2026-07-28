# RentWise：AI Agent 智慧租屋決策平台

可直接用於競賽 Live Demo 的完整 MVP：

- React + Vite 前端
- FastAPI 後端
- LangGraph Multi-Agent 工作流
- Source Planning / Data Loader / Location / Cost / Property / Suitability /
  Decision Explanation Agents
- 無 OpenAI API Key 也能完整展示
- 有 API Key 時，Decision Explanation Agent 會使用 OpenAI 產生更自然的決策摘要
- 有 API Key 時，可用 Requirement Agent 將一段自然語言轉成表單條件與適配權重
- 目的地欄位會即時將「裕隆城」等地標解析成具體行政區、地址與座標，讓使用者
  在開始搜尋前確認系統理解的位置
- 前端同步展示每個 Agent 的分工、分數與分析結果
- 可依使用者目的地與預算同時載入 591、好房網快租公開刊登，跨站去重後交由 Agent 排名

## 系統流程

```text
使用者需求
   ↓
Source Planning Agent（目的地生活圈＋來源）
   ↓
Load Properties（多平台載入＋去重）
   ├── Location Agent
   ├── Cost Agent
   └── Property Agent
          ↓
   Suitability Agent
          ↓
   Decision Explanation Agent
          ↓
推薦排名 + Agent 決策軌跡
```

> LangGraph 的節點透過共享 State 傳遞資料；三個專業分析 Agent 先執行，再由
> Suitability Agent 計算適配分並完成排名，最後交給 Decision Explanation Agent
> 產生決策說明。

## 1. 最快啟動方式

### Windows PowerShell

後端：

```powershell
cd RentWise\backend
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

另開一個 PowerShell，啟動前端：

```powershell
cd RentWise\frontend
npm install
npm run dev
```

瀏覽器開啟：

```text
http://localhost:5173
```

FastAPI Swagger：

```text
http://localhost:8000/docs
```

## 2. 使用 OpenAI（選用）

編輯 `backend/.env`：

```env
OPENAI_API_KEY=你的金鑰
OPENAI_MODEL=gpt-4.1-mini
```

沒有填 Key 時，整套系統仍可正常運作，畫面會標示 `Rules mode`。
Requirement Agent 的「套用需求」按鈕會停用，但手動表單、數據分析與規則排名
仍可使用。

Requirement Agent 使用 Responses API Structured Outputs，模型只產生預先定義的
租屋欄位；沒有在文字中提到的條件會保留目前表單值。AI 套用後使用者仍可檢查、
修改表單，再決定是否開始搜尋房源。前端會先顯示目的地、預算、通勤與最高權重
的精簡摘要，未在文字中提到的核心欄位會標示為「沿用原設定」；完整表單預設收在
「調整詳細條件」中，不需要重複填寫。

## 3. Docker 啟動（選用）

```bash
docker compose up --build
```

- 前端：http://localhost:5173
- 後端：http://localhost:8000
- API 文件：http://localhost:8000/docs

## 4. 建議操作

可以直接使用預設條件：

- 月租總預算：15,000 元
- 目的地：政治大學
- 最長通勤：25 分鐘
- 需要對外窗
- 偏好安靜
- 需要便利商店
- 不想爬太多樓梯

按下「啟動 Multi-Agent 分析」後，展示：

1. Source Planning Agent 依使用者輸入的目的地決定生活圈及搜尋來源
2. Data Loader 同時載入 591、好房網快租即時公開刊登並跨站去重
3. Location Agent 比較地點與生活機能
4. Cost Agent 保留已揭露費用，並以 OpenAI 公開搜尋＋結構化輸出補估所在地
   的管理費、水費、電價與用電量
5. Property Agent 使用 OpenAI 圖片輸入，結合刊登坪數判讀窗戶與空間觀感
6. Suitability Agent 根據個人偏好計分
7. Decision Explanation Agent 使用 OpenAI，讀取已完成的排名、目的地脈絡與
   所有 Agent 結果，將 AI 估算可信度與客觀分數納入最終取捨說明；不修改名次
8. 點「查看地圖與超商」後，載入目的地、前 6 名房源，以及房源
   500 公尺內的 OpenStreetMap 便利商店與停車設施

地圖右欄的目的地與房源可點選；選取後地圖會移動到該點並以動畫光圈標示。
便利商店與停車設施僅以數量、圖例及地圖標記呈現。若抽象目的地仍無法精確定位，
地圖會使用候選
房源生活圈中心作為可點選的代表點，並明確標示它不是精確目的地。

Property Agent 不向使用者顯示不透明的房況分數，而是將使用者條件逐項標示為
「符合」、「不符合」或「待確認」，推薦卡只顯示精簡條件標籤；展開 Agent
分析後才顯示每項判斷所依據的原始刊登證據。待確認項目不會直接視為不符合：
房屋條件的未知資料不給中性分，也不視為不符合；已知條件符合率與資料完整度
分開顯示。完整公式、必要條件資格與版本說明見 [`SCORING.md`](SCORING.md)。
若有實際刊登圖片，Property Agent 會以視覺模型判斷照片中是否清楚看到窗戶，
並結合刊登坪數描述空間是寬敞、適中或緊湊。照片沒拍到窗戶不等於沒有窗戶；
縮圖、廣角鏡或照片不足會降低可信度。

使用者可在前端調整通勤、成本、房屋條件與噪音的相對權重。四項永遠合計
100%，可先鎖定不希望改變的項目；拖動其他滑桿時，系統只重新分配未鎖項目。
每張推薦卡可展開查看公式版本、原始資料比例、四項原始分數、原始／有效權重、
加權貢獻、證據覆蓋率、必要條件資格與資料完整度。

## 5. API

### 健康檢查

```http
GET /api/health
```

### 解析目的地

```http
POST /api/resolve-destination
Content-Type: application/json

{"query": "裕隆城"}
```

回應包含具體顯示名稱、縣市、行政區、地址、經緯度與資料來源。前端推薦請求會
沿用這組已確認的地址與座標，避免顯示與實際通勤計算使用不同位置。

### 取得房源

```http
GET /api/properties
```

### 執行推薦

```http
POST /api/recommend
Content-Type: application/json
```

推薦請求範例：

```json
{
  "budget": 15000,
  "destination": "政治大學",
  "max_commute_minutes": 25,
  "needs_window": true,
  "noise_preference": "quiet",
  "needs_elevator": false,
  "needs_convenience_store": true,
  "max_floor_without_elevator": 3,
  "preferences": ["採光良好", "可開伙"],
  "weights": {
    "location": 30,
    "cost": 30,
    "property": 25,
    "noise": 15
  },
  "property_source": "multi",
  "commute_mode": "transit_walk",
  "needs_parking": false,
  "needs_rental_subsidy": false
}
```

`property_source` 可使用：

- `multi`：同時讀取 591 與好房網快租，合併相同租金與地址的重複刊登（預設，需要網路）
- `591`：只依目的地讀取 591 即時公開刊登（需要網路）

### 將自然語言轉成租屋條件

```http
POST /api/parse-requirements
Content-Type: application/json
```

請求包含 `text` 與目前的 `current` 表單。回應會提供經 schema 驗證的
`requirements`、一句解析摘要，以及需要使用者確認的 `assumptions`。

```json
{
  "text": "我在輔大上課，預算一萬五，30 分鐘內到，通勤最重要，一定要有窗。",
  "current": {
    "budget": 15000,
    "destination": "政治大學",
    "max_commute_minutes": 25,
    "property_source": "multi"
  }
}
```

目的地目前可輸入台灣縣市、已建立對照的行政區，以及常見大學／地標。行政區
名稱若可能出現在多個縣市（例如「大安區」），請輸入「台北市大安區」這類完整
名稱。各租屋平台列表頁未必揭露管理費、水電、對外窗、電梯及噪音等完整資訊；
RentWise 會把未揭露欄位標示為待確認。Location Agent 會先將房源地址與目的地
定位，再透過 Valhalla 行人路網計算步行通勤時間與距離，並把通勤結果納入推薦
排名。設定 TDX Client ID 與 Client Secret 後，系統會優先查詢公車、台鐵、捷運
與輕軌，第一哩及最後一哩皆設定為最多 15 分鐘步行；TDX 沒有適合班次時，改用
Valhalla 真實步行路網。若路由服務暫時無法使用，則清楚標示為地理距離步行
推估，不會用汽車時間假冒大眾運輸時間。最終仍應開啟原始刊登向出租方確認。
目前未整合 Facebook 社團；多來源 Adapter 僅使用可公開查詢的租屋網站。

`commute_mode` 可設為 `transit_walk` 或 `drive`。駕車模式使用 Valhalla `auto`
道路路網時間並與大眾運輸／步行結果並列，但不宣稱是即時塞車時間。
`needs_parking` 啟用時會查詢房源 500 公尺內的 OpenStreetMap 停車設施，並將
停車距離分數納入 Location 分數。通勤、使用者有勾選的超商與停車項目會平均
分配 Location 權重；資料未知的項目不參與，也不以猜測值扣分。
`needs_rental_subsidy` 啟用時，Property Agent 會將刊登中的租補資訊標成符合、
不符合或待確認；只有刊登明確不配合時才視為必要條件衝突。

目的地可輸入唯一行政區簡稱，例如「內湖」會解析為台北市內湖區；若名稱在不同
縣市重複（例如「大安」），系統仍會要求補上縣市，避免查錯生活圈。

便利商店不只依賴刊登文字。推薦分析期間會用已定位的房源座標查詢
OpenStreetMap，在每間房 500 公尺內找到的超商會直接納入 Location Agent；
公共 Overpass 節點暫時失效時才保留刊登資料並標示未知。

房源載入會排除標題或物件類型明確屬於車位出租、且沒有住宅房型訊號的刊登；
「三房附車位」等可居住房源仍會保留。591 與好房網的刊登文字也會逐項辨識
含水費、固定管理費、每度電價與租補標示，多來源重複房源會保留揭露較完整的
費用與租補資訊。

Data Loader 在通勤與排名前會先做可居住用途審核。純車位、置物空間、儲藏室、
迷你倉、倉庫或明確禁止居住／過夜的刊登會被排除；透明規則無法確認的物件，
再由 OpenAI 讀取完整刊登頁做結構化分類。只有中或高可信度的非住宅判定會自動
排除，證據不足的物件保留為待確認，住宅附車位或附儲藏室不會因此被刪除。

Property Agent 會進一步讀取原始刊登詳情頁，讓 OpenAI 依使用者條件理解同義詞、
縮寫、否定與委婉寫法。每項 AI 判定都必須保留原文證據、可信度與
符合／不符合／待確認狀態；無法讀取詳情頁、OpenAI 暫時不可用或語意不明時，
自動退回透明關鍵字規則，不會由 AI 猜測或直接產生適配分。
使用者有設定安靜程度時，Property Agent 也會從刊登原文產生低、中、高或未知的
噪音證據與可信度；Suitability Agent 只依這份證據套用公開公式，不自行解讀文字。

### 取得地圖與附近超商／停車設施

```http
POST /api/map-context
Content-Type: application/json
```

地圖使用 Leaflet 與 OpenStreetMap 圖磚，地址定位使用 Nominatim，便利商店與
停車設施查詢使用 Overpass API。Location Agent 在推薦分析時已取得的設施座標會
直接傳給地圖重用；只有該類設施尚未查詢完成時，地圖 API 才會補查。地圖上的虛線
表示相對位置，不是實際道路路線或通勤時間。

## 6. 專案結構

```text
RentWise/
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   ├── data/
│   │   ├── graph/
│   │   ├── models/
│   │   ├── services/
│   │   └── main.py
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   ├── package.json
│   └── vite.config.js
└── docker-compose.yml
```

## 7. 競賽簡報可用說法

RentWise 並非由單一聊天機器人一次產生答案，而是讓多個具有明確責任的 Agent
讀取同一份租屋需求與房源資料。LangGraph 負責管理狀態與節點流程，專業 Agent
分別完成地點、成本及房況分析，再由 Suitability Agent 依使用者偏好計算適配度
並排名，最後交給 Decision Explanation Agent 產生決策說明。

## 8. 下一步可擴充

- 增加其他具公開搜尋頁或正式 API 的租屋平台 Adapter
- Places API：搜尋便利商店、超市、醫院
- PostgreSQL：儲存房源、使用者偏好與歷次推薦
- Vision：分析房間照片的採光、窗戶、霉斑與設備
- 房源網址爬取與自動結構化
- WebSocket / SSE：即時推送 Agent 執行狀態
