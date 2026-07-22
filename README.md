# RentWise：AI Agent 智慧租屋決策平台

可直接用於競賽 Live Demo 的完整 MVP：

- React + Vite 前端
- FastAPI 後端
- LangGraph Multi-Agent 工作流
- Location / Cost / Property / Suitability / Comparison Agents
- 內建 5 筆政大周邊範例房源
- 無 OpenAI API Key 也能完整展示
- 有 API Key 時，Comparison Agent 會使用 OpenAI 產生更自然的決策摘要
- 前端同步展示每個 Agent 的分工、分數與分析結果

## 系統流程

```text
使用者需求
   ↓
Load Properties
   ├── Location Agent
   ├── Cost Agent
   └── Property Agent
          ↓
   Suitability Agent
          ↓
   Comparison Agent
          ↓
推薦排名 + Agent 決策軌跡
```

> LangGraph 的節點透過共享 State 傳遞資料；三個專業分析 Agent 先執行，再由 Suitability Agent 計算整體適配分數，最後交給 Comparison Agent 排名。

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

沒有填 Key 時，整套系統仍可正常運作，畫面會標示 `Demo rules mode`。

## 3. Docker 啟動（選用）

```bash
docker compose up --build
```

- 前端：http://localhost:5173
- 後端：http://localhost:8000
- API 文件：http://localhost:8000/docs

## 4. Demo 建議操作

可以直接使用預設條件：

- 月租總預算：15,000 元
- 目的地：政治大學
- 最長通勤：25 分鐘
- 需要對外窗
- 偏好安靜
- 需要便利商店
- 不想爬太多樓梯

按下「啟動 Multi-Agent 分析」後，展示：

1. Location Agent 比較通勤與生活機能
2. Cost Agent 計算真實月支出
3. Property Agent 檢查硬體條件與風險
4. Suitability Agent 根據個人偏好計分
5. Comparison Agent 排名並解釋取捨

## 5. API

### 健康檢查

```http
GET /api/health
```

### 取得房源

```http
GET /api/properties
```

### 執行推薦

```http
POST /api/recommend
Content-Type: application/json
```

範例：

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
  "preferences": ["採光良好", "可開伙"]
}
```

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

RentWise 並非由單一聊天機器人一次產生答案，而是讓多個具有明確責任的 Agent 讀取同一份租屋需求與房源資料。LangGraph 負責管理狀態與節點流程，專業 Agent 分別完成地點、成本及房況分析，再由 Suitability Agent 依使用者偏好計算適配度，最後交給 Comparison Agent 進行跨房源比較與決策說明。

## 8. 下一步可擴充

- Google Maps Distance Matrix / Routes API：取得真實通勤時間
- Places API：搜尋便利商店、超市、醫院
- PostgreSQL：儲存房源、使用者偏好與歷次推薦
- Vision：分析房間照片的採光、窗戶、霉斑與設備
- 房源網址爬取與自動結構化
- WebSocket / SSE：即時推送 Agent 執行狀態
