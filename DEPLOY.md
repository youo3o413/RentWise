# 公開部署

專案根目錄的 `Dockerfile` 會建置 React 前端，再由 FastAPI 提供網頁與 API；部署成一個服務即可。原本的 `docker-compose.yml` 保留供本機開發。

## 支援 Docker 的主機

- Build context：`RentWise` 專案根目錄。
- Dockerfile：根目錄的 `Dockerfile`。
- 監聽埠：讀取主機的 `PORT`，預設 `8000`。
- 健康檢查：`/api/health`。
- 將持久化磁碟掛載到 `/data`，保存推薦流程的 SQLite checkpoint。未掛載時，重建容器會失去先前的推薦流程。
- 使用單一執行個體；目前 SQLite 設計不支援各自持有磁碟的多副本部署。

透過平台的環境變數設定 `OPENAI_API_KEY`（選用）、`OPENAI_MODEL`（選用）、`TDX_CLIENT_ID` 與 `TDX_CLIENT_SECRET`（選用）。不要將 `.env` 上傳到原始碼倉庫；映像建置已排除 `.env`、本機資料庫與虛擬環境。

前端正式建置預設呼叫同一網址下的 `/api`，不需要設定 `VITE_API_BASE_URL`。本機開發仍預設使用 `http://localhost:8000`。

## Railway 部署（目前選用）

目前專案：`RentWise`；服務：`rentwise`；環境：`production`。

- 網站：https://rentwise-production-c1d1.up.railway.app
- 管理：https://railway.com/project/80a03072-acfb-4108-abd8-4c29b23ce909
- Volume 掛載位置：`/data`。
- 首次部署採規則模式，未上傳本機 `.env` 或啟用付費 API 金鑰。
- 已依使用者授權將 OpenAI 金鑰設定為 Railway 後端環境變數，使用 `gpt-4.1-mini`；線上健康檢查與 AI 需求解析已驗證成功。金鑰不存入本文件或前端。
- 現行版本預設載入 18 筆台大周邊虛構房源，`LIVE_LISTING_SOURCES_ENABLED=false`，不抓取 591 或好房網；資料來源與 AI 是否啟用是獨立設定。

根目錄的 `railway.json` 已指定 Dockerfile 建置與 `/api/health` 健康檢查。

1. 使用 Railway CLI 登入：`npx @railway/cli login`。
2. 在 `RentWise` 目錄執行 `npx @railway/cli init` 建立專案，或用 `npx @railway/cli link` 連結既有專案。
3. 建立並選取 RentWise 服務，新增 Volume，掛載路徑設為 `/data`。保持單一副本。
4. 在服務的 Variables 設定需要的 API 金鑰；不設定時先以規則模式部署。
5. 在 `RentWise` 目錄執行 `npx @railway/cli up` 上傳與部署。
6. 部署成功後，在服務 Settings → Networking 產生公開網域；目標埠使用 Railway 注入的 `PORT` 值（目前服務為 `8080`），可從啟動日誌確認。
7. 開啟公開網址及 `/api/health` 確認正常，再測試搜尋。

若改由 GitHub 部署，請以 `RentWise` 專案目錄為服務根目錄，並讓 Railway 指向該目錄內的 `railway.json`。

參考：[Railway CLI](https://docs.railway.com/cli)、[部署設定](https://docs.railway.com/config-as-code/reference)。

## Render 部署步驟（替代方案）

1. 將專案推送到自己的 Git 儲存庫，再到 Render 建立 **Web Service** 並連結儲存庫。
2. 若儲存庫根目錄就是本專案，Root Directory 留空；若儲存庫內另有 `RentWise/`，則填 `RentWise`。
3. Language 選 **Docker**，Dockerfile Path 填 `./Dockerfile`。
4. Health Check Path 填 `/api/health`，依需求設定上述環境變數，然後部署。
5. 部署成功後開啟平台提供的 HTTPS 網址，確認首頁與 `/api/health` 都能正常回應，再測試搜尋。

免費方案可供展示，但閒置 15 分鐘會休眠，且重啟或重新部署會遺失 SQLite 資料。需要持續保存推薦流程時，請選擇支援持久化磁碟的付費服務並掛載 `/data`。

參考：[Render Docker 部署](https://render.com/docs/docker)、[免費服務限制](https://render.com/docs/free)。

## 本機驗證正式映像

```sh
docker build -t rentwise .
docker run --rm -p 8000:8000 --env-file backend/.env -v rentwise-data:/data rentwise
```

開啟 `http://localhost:8000`；健康檢查為 `http://localhost:8000/api/health`。

公開服務目前沒有登入限制，任何訪客皆可啟動分析；若設定付費 API 金鑰，這些請求會使用該金鑰的額度。
