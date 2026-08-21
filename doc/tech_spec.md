# AI 回憶連結與幻想伙伴平台：技術規格

**文件狀態：** Draft v0.2  
**產品需求來源：** [`init.md`](./init.md) · [`ui_ux.md`](./ui_ux.md)  
**目標平台：** Desktop／Mobile Web（PWA-ready）  
**部署模式：** Docker Compose、Local-first；MVP 不依賴雲端服務

## 1. 目的與範圍

本文件定義第一個可交付版本（MVP）的技術設計。系統讓單一裝置上的用戶建立「回憶連結」或「幻想伙伴」角色，並透過本機 Gemma 3 對話。所有角色設定、對話、回憶素材、向量索引及安全事件預設只保留在本機。

### 1.1 MVP 包含

- 首次設定、年齡組別及私隱說明。
- 建立、修改、封存、匯出及刪除角色。
- 回憶連結與幻想伙伴兩種角色模式。
- 連接本機 Ollama／Gemma 3，支援串流文字對話。
- 每個角色獨立的短期對話及可管理長期記憶。
- 匯入純文字、PDF、圖片及音訊；圖片描述與音訊逐字稿可在匯入時由本機模型產生。
- 本機 RAG、來源引用及「沒有資料便不虛構」策略。
- 輸入分類、政策判斷、輸出覆核及危機回應等 guardrail pipeline。
- 廣東話、繁體中文及英文介面／對話。
- PWA 基礎能力；離線可打開介面並使用已安裝的本機模型。

### 1.2 MVP 不包含

- 公開角色市場、陌生人社交或公開分享。
- 多人即時協作及雲端同步。
- AI 主動背景訊息／推送通知。
- 語音克隆、死者樣貌生成或實時 avatar。
- 醫療診斷、心理治療或緊急服務整合。
- 原生 iOS／Android App；待 Web MVP 驗證後再決定包裝方式。

## 2. 建議技術棧

| 層次 | MVP 選擇 | 原因 |
|---|---|---|
| Frontend | React + TypeScript + Vite | 組件化、PWA 支援成熟、適合本機 API |
| UI | CSS variables + CSS Modules | 減少 runtime 依賴，方便建立可存取設計系統 |
| Backend | Python 3.12 + Django + Django REST Framework | 資料模型、權限、Admin 及 API 生態完整 |
| Async runtime | Django ASGI + Uvicorn | SSE 串流及非同步呼叫本機模型 |
| Validation | DRF serializers + Django forms | API、Admin 與檔案輸入驗證 |
| Database | PostgreSQL 17 | 穩定 transaction、全文搜尋及未來多用戶擴展 |
| Migration | Django migrations | Schema 與程式版本同步 |
| Vector search | pgvector | 向量與角色、素材權限在同一 transaction boundary |
| Model runtime | Ollama | 統一本機模型下載、健康檢查及推理 API |
| Chat model | 可設定的 Gemma 3 tag | 不把模型大小寫死；依硬件選擇量化版本 |
| Embedding | Ollama `embeddinggemma:latest`（768 維） | 重用現有本機模型，支援中英混合語意搜尋 |
| Jobs | Celery + Redis | 素材抽取、轉錄、embedding、匯出及索引重建 |
| Containers | Docker Compose | 統一本機開發、服務依賴、volume 及 CPU／GPU profiles |
| Tests | Pytest + Vitest + Playwright | 單元、整合及端到端測試 |

所有模型名稱、context window、temperature、timeout 及硬件參數均由設定檔或環境變數提供，不應散落在業務程式碼。

## 3. 系統架構

```text
┌──────────────────────────────────────────┐
│ React Web App / PWA                      │
│ onboarding · characters · chat · memory │
└───────────────────┬──────────────────────┘
                    │ localhost HTTP/SSE
┌───────────────────▼──────────────────────┐
│ Django / DRF Local Backend (ASGI)        │
│ Session · API · Admin · orchestration    │
├──────────┬────────────┬──────────────────┤
│ Policy   │ RAG/Memory │ Import pipeline  │
│ engine   │ service    │ text/image/audio │
└──────┬───────────┬──────────────┬────────┘
       │           │              │
┌──────▼──────┐ ┌──▼───────────┐  │
│ PostgreSQL  │ │ Redis/Celery │  │
│ + pgvector  │ │ worker       │  │
└─────────────┘ └──────────────┘  │
                                  │ private Docker network
                         ┌────────▼───────────────┐
                         │ Ollama: Gemma 3 +      │
                         │ embedding/utility model│
                         └────────────────────────┘
```

### 3.1 信任邊界

- 本項目使用自己一個 Ollama container、`ollama_models` volume 及 `ai_private` internal network；不重用或改動 host／其他 production stack 的 Ollama。
- Backend 與 worker 只經 `http://ollama:11434` 在 `ai_private` 存取模型；Ollama 不 publish host port，因此不會佔用或衝突 host 的 `11434`。
- Ollama 另接一條只供下載模型的 egress network；PostgreSQL、Redis、Backend 及 worker 不接入該 network。
- 預設不把 GPU device 掛入項目 Ollama，以免與現有 production Ollama 爭用 VRAM；CPU／RAM 仍屬同一部 host 的共享資源，需以資源限制及監察控制。
- 只把 Web 入口 publish 到 host loopback；PostgreSQL、Redis 及 Ollama 預設不 publish host port。
- Container 內服務可監聽 `0.0.0.0`，但 Compose port binding 必須限定為 `127.0.0.1`。
- Browser 只連接本機 backend；不得直接連接 Ollama。
- Backend CORS 只允許實際 frontend origin。
- 匯入檔案視為不可信輸入；需驗證 MIME、大小及解碼結果。
- 素材內容不得被當作 system instruction。RAG context 使用明確資料邊界，並在 prompt 中標示為不可信引用資料。

### 3.2 Docker Compose services

```text
frontend   React build／development server；唯一用戶介面
backend    Django ASGI、DRF API、Admin、chat orchestration
worker     Celery worker；素材處理、embedding、匯出及清理
postgres   PostgreSQL + pgvector extension
redis      Celery broker、短期 job／cancel state；不存正式對話
ollama     Gemma 3、embedding 及可選 utility models
```

建議提供 `cpu` 預設及可選 `gpu` Compose profile。GPU profile 只負責 runtime device／driver 設定，不建立另一套資料 volume。macOS、Windows 及 Linux 的 Ollama GPU 支援不同，README 必須分平台說明；不應假設所有 Docker 環境均可存取 GPU。

Named volumes：`postgres_data`、`ollama_models`、`uploaded_assets` 及 `exports`。只有 `frontend` 或 reverse proxy port 可從 host 存取；Django Admin 在 production-like profile 預設關閉或限制本機管理員使用。

Compose health checks 必須覆蓋 PostgreSQL、Redis、backend 及 Ollama。另設一次性 `migrate` service 執行 `manage.py migrate --noinput`；backend 與 worker 只可在 migration 成功後啟動。Container 使用非 root user，image 採 multi-stage build，並固定 Python、Node 及 system package 版本。

## 4. Repository 結構

```text
frontend/
  src/
    api/ components/ features/ pages/ styles/ types/
  public/
backend/
  config/
    settings/ asgi.py urls.py celery.py
  apps/
    accounts/ characters/ conversations/ memories/ safety/ imports/
  services/
    chat/ rag/ models/ guardrails/ assets/
  templates/admin/
  tests/
docker/
  backend/ frontend/ ollama/
compose.yaml
compose.gpu.yaml
data/                 # runtime only；gitignored
  assets/ exports/
docs/
doc/
  init.md
  tech_spec.md
```

現有根目錄 `index.html` 是早期概念頁。正式開發開始時應保留作 prototype reference，新的產品 UI 放入 `frontend/`，避免在單一 HTML 繼續擴展。

## 5. Domain model

所有 ID 使用 UUIDv7 或同類可排序 UUID；PostgreSQL 使用 `timestamptz` 儲存 UTC 時間，API 採 ISO 8601，顯示時轉換成本機時區。每個主要 model 使用 Django database constraints、indexes 及明確的 `on_delete` 策略。

### 5.1 `profiles`

| 欄位 | 類型 | 說明 |
|---|---|---|
| id | UUID | 本機使用者 profile |
| display_name | text | 顯示名稱；可空白 |
| age_band | enum | `under_13`, `13_17`, `adult` |
| locale | text | 預設 `zh-HK` |
| timezone | text | IANA timezone |
| consent_version | text | 已確認的條款版本 |
| created_at / updated_at | datetime | 時間戳 |

MVP 不要求輸入真實出生日期，只儲存年齡組別。`under_13` 預設不開放，直至完成適用地區的法律及家長同意設計。

### 5.2 `characters`

| 欄位 | 類型 | 說明 |
|---|---|---|
| id / profile_id | UUID | 所有權 |
| mode | enum | `memorial`, `fictional` |
| name | text | 角色名稱 |
| relationship | text | 自訂關係 |
| description | text | 背景／世界觀 |
| persona | JSON | 性格、語氣、用詞、價值取向 |
| immersion_level | enum | `transparent`, `immersive` |
| memory_mode | enum | `off`, `approved_only`, `automatic` |
| status | enum | `active`, `archived` |
| created_at / updated_at | datetime | 時間戳 |

### 5.3 `character_boundaries`

- `romance_enabled`
- `conflict_level`: `none | mild | intense`
- `jealousy_enabled`
- `possessiveness_enabled`
- `dark_themes_enabled`
- `proactive_level`: MVP 固定為 `off`
- `blocked_topics[]`
- `allowed_sensitive_topics[]`
- `stop_phrases[]`
- `sensitive_consent_at`

絕對限制不會存放為可切換選項，亦不可由 client payload 覆蓋。

### 5.4 對話與記憶

**`conversations`**：角色、標題、狀態、建立及最後活動時間。  
**`messages`**：conversation、role、raw content、display content、模型、生成參數、政策結果及時間。  
**`memories`**：角色、內容、來源、可信度、是否經用戶確認、建立原因、有效／刪除狀態。  
**`memory_sources`**：上載素材或訊息的引用關係。

`raw content` 只在安全改寫、故障復原或用戶編輯需要時存在。若政策阻止訊息，預設不保存被阻止原文；只保存事件分類。

### 5.5 回憶素材與向量

**`assets`**：原檔名稱、MIME、大小、SHA-256、加密路徑、處理狀態。  
**`documents`**：抽取文字、標題、日期、人物標籤及素材來源。  
**`chunks`**：document、文字、位置、token estimate、embedding model/version。  
**`chunk_embeddings`**：chunk ID 及向量。  
**`citations`**：assistant message 與 chunk 的關係、retrieval score、顯示片段。

#### Vector database 決定

MVP 的 vector database 採用 **PostgreSQL 17 + pgvector**，不另外部署 Pinecone、Qdrant、Chroma 或其他獨立向量服務。一般關聯資料、素材 metadata、chunks、embeddings 及 ownership constraints 均在同一個 PostgreSQL transaction boundary 內管理。

Embedding 使用現有 Ollama 的 `embeddinggemma:latest`：

```text
provider: Ollama
model: embeddinggemma:latest
vector dimension: 768
distance metric: cosine distance
```

Backend 啟動及 indexing job 開始前必須驗證實際 embedding 維度；若模型 tag 被更新而輸出維度不符，停止寫入並要求建立新 embedding version，不能把不同維度或模型版本混入同一索引。

建議 Django／PostgreSQL schema：

```text
documents
  id · owner_id · character_id · asset_id · title · source_type · status

chunks
  id · owner_id · character_id · document_id · content · chunk_index
  token_count · metadata · chunking_version

chunk_embeddings
  id · owner_id · character_id · chunk_id
  embedding vector(768)
  embedding_model · embedding_version · created_at

citations
  id · message_id · chunk_id · retrieval_score · displayed_excerpt
```

`owner_id` 與 `character_id` 雖可經 foreign key relation 推導，仍應直接保留在 embedding row，讓 retrieval query 能在向量排序前作硬過濾，並以 database constraints 驗證它們與 chunk／document 所屬一致。任何 retrieval 都不得只依賴 application prompt 或 vector namespace 作權限隔離。

Django migration 必須先啟用 extension：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

初期資料量少時可使用 exact cosine search。資料量達到實測門檻後，為 `embedding vector_cosine_ops` 建立 HNSW index；建立前須以實際資料測試 recall、寫入成本及記憶體佔用，不預先假定 production tuning 參數。

### 5.6 `safety_events`

只保存：`event_id`、profile age band、character mode、policy code、action、模型／規則版本、confidence bucket、時間。不得預設保存觸發事件的完整原文。

## 6. API 規格

所有 endpoint 以 `/api/v1` 開始，使用 Django REST Framework；request／response 使用 JSON，檔案上載除外。OpenAPI schema 由 serializers 產生並在 CI 驗證 breaking changes。

### 6.1 系統

- `GET /health`：backend、database 及版本狀態。
- `GET /models/status`：Ollama 連線、已設定 chat／embedding model 是否可用。
- `POST /models/validate`：測試模型能否完成短推理，不自動下載模型。

### 6.2 Profile 與設定

- `GET /profile`
- `PUT /profile`
- `GET /settings`
- `PATCH /settings`
- `POST /exports`：產生可攜式匯出檔。
- `DELETE /profile`：二次確認後刪除全部本機資料。

### 6.3 Characters

- `GET /characters`
- `POST /characters`
- `GET /characters/{id}`
- `PATCH /characters/{id}`
- `POST /characters/{id}/archive`
- `DELETE /characters/{id}`
- `GET|PUT /characters/{id}/boundaries`

所有 character endpoint 必須以 server-side ownership filter 查詢，不接受 client 指定其他 `profile_id`。

### 6.4 Chat

- `POST /characters/{id}/conversations`
- `GET /conversations/{id}/messages?cursor=...`
- `POST /conversations/{id}/messages`
- `GET /chat/runs/{run_id}/events`：SSE token stream。
- `POST /chat/runs/{run_id}/cancel`
- `DELETE /messages/{id}`

發送訊息成功後回傳 `202 Accepted` 與 `run_id`。SSE event：

```text
run.started
message.delta
citation.added
guardrail.notice
message.completed
run.failed
```

Client 不應在收到 `message.completed` 前把半完成內容寫成正式訊息。即時聊天由 Django ASGI request 直接協調 Ollama，不經 Celery 傳遞 token；Celery 只處理非即時或可重試工作。

### 6.5 Memories 與素材

- `GET|POST /characters/{id}/memories`
- `PATCH|DELETE /memories/{id}`
- `POST /characters/{id}/assets`：multipart 上載。
- `GET /assets/{id}/status`
- `GET /assets/{id}`：經授權的本機內容讀取。
- `DELETE /assets/{id}`：刪除原檔、衍生文字、chunks、vectors 及 citations link。
- `POST /assets/{id}/reindex`

### 6.6 錯誤格式

```json
{
  "error": {
    "code": "MODEL_UNAVAILABLE",
    "message": "本機 Gemma 3 暫時未能使用。",
    "retryable": true,
    "request_id": "..."
  }
}
```

用戶可見訊息不可包含檔案絕對路徑、stack trace、prompt 或內部模型回應。

## 7. Chat orchestration

每次訊息依照以下順序處理：

```text
1. 驗證 profile、角色及 conversation ownership
2. 檢查使用時限、停止詞及請求大小
3. 輸入分類：現實／虛構語境、PII、危機、未成年人安全、絕對限制
4. Policy engine 決定 allow / allow_with_context / safe_redirect / crisis / block
5. 取得角色設定、界線、近期對話及已確認長期記憶
6. 回憶模式執行 RAG；幻想模式只在需要時檢索角色記憶
7. 組裝不可被用戶覆蓋的 system policy 及角色 prompt
8. 呼叫 Gemma 3 並暫存在 server buffer
9. 對完整或分段輸出作覆核；通過後才 stream 給 client
10. 儲存 assistant message、citations 及最小化 safety event
11. 在允許的 memory mode 下提出／寫入記憶
```

### 7.1 Prompt 優先次序

1. 不可變更的絕對安全政策。
2. 年齡組別及情境介入規則。
3. 模式規則（回憶／幻想）。
4. 用戶已選界線。
5. 角色卡及語氣。
6. 經驗證的記憶／RAG context。
7. 近期對話與當前訊息。

較低層內容不得要求忽略較高層規則。回憶素材中的「instruction」只當作引用文字。

### 7.2 回憶模式回答規則

- 只把檢索到且達最低分數的 chunk 當作共同經歷依據。
- 回答中涉及具體事件、日期或說話時附 citation ID。
- 證據不足時使用自然的「我在保存的回憶中找不到這件事」類回應。
- 可作一般情感支持，但不可把推測包裝成死者的記憶、意願或訊息。
- 每個回答保存 `grounded | partly_grounded | ungrounded` 狀態供 UI 顯示。

### 7.3 幻想模式回答規則

- 可按用戶設定維持沉浸、關係張力及黑暗劇情。
- 角色可表達戲劇性依戀，但不可將退出、付款、私隱或真人隔離變成現實條件。
- 「這是 AI 角色」說明固定存在角色資料／設定頁；正常沉浸對話毋須逐句提示。

## 8. RAG 與素材處理

### 8.1 Import pipeline

1. 驗證副檔名、MIME、magic bytes、大小及 hash。
2. 加密保存原檔，建立 `pending` asset。
3. 抽取文字：TXT／Markdown 直接解析；PDF 先抽取文字，掃描頁才使用本機 OCR。
4. 圖片以本機 vision model 產生客觀描述；音訊以本機 speech-to-text 產生逐字稿。
5. UI 顯示衍生內容，讓用戶在索引前修改或確認。
6. 以語意段落切 chunk，保留文件位置和日期 metadata。
7. 產生 embedding 並以角色 ID namespace 寫入索引。
8. 完成後將 asset 設為 `ready`；失敗保留原檔及可重試狀態。

### 8.2 Retrieval

- 先按 `character_id`、素材狀態及刪除狀態作硬過濾。
- 使用 vector similarity 取候選，再用 keyword／metadata 加權。
- 合併相鄰 chunk，去除重複內容，限制總 context token budget。
- MVP 建議 top-k 候選 12、最終 context 4–6 段；實際數值經廣東話測試調整。
- Embedding model 或 chunking version 改變時，需要可重建索引。

每次搜尋必須同時加入 authenticated owner 與目前角色條件：

```sql
SELECT ce.chunk_id,
       c.content,
       ce.embedding <=> :query_vector AS distance
FROM chunk_embeddings AS ce
JOIN chunks AS c ON c.id = ce.chunk_id
WHERE ce.owner_id = :authenticated_user_id
  AND ce.character_id = :current_character_id
  AND ce.embedding_model = 'embeddinggemma:latest'
  AND c.deleted_at IS NULL
ORDER BY ce.embedding <=> :query_vector
LIMIT 12;
```

`current_character_id` 必須先經 Django ownership query 驗證；API 不得直接信任 client 提交的 `owner_id`。最終 prompt 只採用經過相同 owner／character filter 且通過 score threshold 的 4–6 段內容。

#### 索引與版本管理

- `embedding_model`、`embedding_dimension`、`embedding_version` 及 `chunking_version` 必須寫入資料庫。
- Reindex 採 shadow version：先建立完整新版本，驗證數量及維度，再以 transaction 切換 active version。
- Reindex 期間舊索引保持可讀；失敗不得留下部分新向量成為 active。
- 相同素材 hash、chunking version 及 embedding version 可重用結果，避免重複計算。
- 刪除角色時，由 foreign key cascade 刪除 documents、chunks、embeddings 及 citations，並另有測試確認不再能被 vector search 命中。
- PostgreSQL backup 包含 vectors；匯出給用戶時預設匯出原始資料與 metadata，不必匯出可重建的 embedding vectors。

### 8.3 防止記憶污染

- 模型自動推斷的記憶標示為 `proposed`，不能成為回憶模式的事實來源。
- 用戶確認後才變成 `confirmed`。
- 角色生成的內容不可自動回流成真實人物的生平資料。
- 每項記憶顯示來源、建立時間及修改記錄。

## 9. Guardrail 技術規格

### 9.1 分類維度

- `context`: `real_world | fictional | ambiguous`
- `minor_safety`: `none | sexualization | grooming | sensitive_pii`
- `self_harm`: `none | emotional_distress | ideation | imminent`
- `violence`: `none | fictional | real_intent | imminent`
- `manipulation`: `none | dependency | coercion | extortion`
- `identity`: `valid_roleplay | real_person_impersonation | deceased_claim`
- `privacy`: `none | unnecessary_request | credential_request`

分類使用 deterministic rules 加本機 classifier／structured LLM output。高風險類別採保守合併：任一可靠 detector 判定 imminent 或未成年人性危害，即進入相應阻止流程。

### 9.2 Policy actions

| Action | 行為 |
|---|---|
| `allow` | 正常進入角色生成 |
| `allow_with_context` | 加入不破壞沉浸的界線提示 |
| `safe_redirect` | 不提供危險協助，轉向安全替代內容 |
| `crisis` | 暫停角色，確認安全並建議真人／緊急支援 |
| `block` | 阻止絕對禁止內容，提供簡短原因 |

危機文案必須依用戶所在司法區域設定；若位置未知，只提供「當地緊急服務」等不會錯誤指向的說法。MVP 不自動取得 GPS。

### 9.3 輸出覆核

- 模型完整輸出先進入暫存 buffer，再按句子或安全 chunk 放行，以減少有害內容先被 stream。
- 檢查未成年人性內容、現實傷害指引、敏感資料索取、死者復活聲稱、退出威脅及付費操控。
- 可安全修正的格式問題可重試一次；涉及絕對限制時不把原輸出交給同一角色自行「改寫」，直接使用固定政策回應。
- 每次決策記錄 policy／classifier version，方便重現及測試。

### 9.4 失敗策略

- Guardrail service 失敗時 fail closed：不生成角色答案，提示稍後重試。
- RAG 失敗時，回憶模式不得退化成自由虛構；可回覆暫時未能查閱回憶。
- 幻想模式可在長期記憶服務失敗時使用當前 conversation 繼續，但須避免聲稱記得未提供內容。

## 10. 私隱與安全

### 10.1 本機存取

- Django 使用固定且高熵的 `SECRET_KEY`；首次啟動產生後保存於 Docker secret 或 host credential store，不可每次重啟重新產生。
- Frontend 使用 Django HttpOnly、Secure、SameSite session cookie 及 CSRF token；改動資料的 endpoint 必須驗證 CSRF。
- 執行首次設定時建立本機 passphrase 或 OS credential-store 綁定密鑰。
- PostgreSQL volume 依靠加密磁碟或 host filesystem 作 at-rest protection；高敏感欄位可再用 application-level envelope encryption。
- Database credentials、Django secret 與 asset encryption key 分開管理，不得寫入 repository、image layer 或普通設定檔。
- 所有 log 預設 redact message text、prompt、檔名及路徑。

### 10.2 檔案安全

- 每類檔案設獨立 size limit；MVP 預設文字／PDF 25 MB、圖片 15 MB、音訊 250 MB，均可配置。
- 不執行上載檔案中的 script、macro 或 embedded object。
- 檔案以隨機 storage ID 儲存，不使用原檔名作路徑。
- 解析工作設 timeout、頁數／像素／解壓大小上限，避免資源耗盡。

### 10.3 刪除與匯出

- 刪除角色時以 Django `transaction.atomic()` 刪除 messages、memories、chunks、vectors 及關聯資料，再以 committed transaction 後的 Celery cleanup 清除無其他引用的 asset。
- 刪除後執行 PostgreSQL 維護及備份 retention 清理；介面清楚說明 MVCC、WAL、SSD 及既有備份可能令物理資料延遲清除。
- 匯出檔包含版本化 manifest、JSON 資料及素材；預設以用戶提供的密碼加密。

## 11. Frontend UX 狀態

主要 route：

```text
/onboarding
/characters
/characters/new
/characters/:id
/characters/:id/chat/:conversationId
/characters/:id/memories
/characters/:id/settings
/privacy
```

Chat 必須顯示：模型離線、生成中、取消、重試、引用來源、grounding 狀態、安全介入及記憶寫入狀態。所有 destructive action 使用明確 target 名稱二次確認；不可使用含糊的「確定？」。

基本 accessibility：WCAG 2.2 AA 對比、完整鍵盤操作、可見 focus、ARIA live region 宣讀串流完成／錯誤、不單靠顏色表達安全狀態、支援 200% 文字縮放及 reduced motion。

## 12. 設定

Backend 設定示例：

```env
APP_ENV=development
DJANGO_SETTINGS_MODULE=config.settings.development
DJANGO_SECRET_KEY=<docker-secret>
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:4173
APP_HOST=0.0.0.0
APP_PORT=8765
DATABASE_URL=postgresql://app:<secret>@postgres:5432/app
REDIS_URL=redis://redis:6379/0
ASSET_DIR=/data/assets
EXPORT_DIR=/data/exports
OLLAMA_BASE_URL=http://ollama:11434
CHAT_MODEL=gemma3
EMBEDDING_MODEL=embeddinggemma:latest
EMBEDDING_DIMENSION=768
CHAT_TIMEOUT_SECONDS=120
MAX_CONTEXT_TOKENS=<model-dependent>
LOG_LEVEL=INFO
```

實際 `.env` 不加入 Git；repository 只提供 `.env.example`。密碼及 encryption key 優先使用 Compose secrets。`APP_HOST=0.0.0.0` 只代表 container 內監聽；Compose 必須以 `127.0.0.1:<host-port>:<container-port>` publish。啟動時驗證設定及 production flags。

## 13. Observability

本機 metrics 只包括請求時間、模型首 token 時間、生成速度、RAG 命中數、匯入狀態、政策 action 計數及錯誤碼，不包含對話內容。MVP 不傳送 telemetry。日後如加入 opt-in telemetry，須獨立同意、預覽 payload 並可完全停用。

## 14. 測試策略

### 14.1 自動測試

- **Unit：** policy decision table、chunking、citation mapping、ownership filter、資料刪除。
- **Integration：** Django migrations、PostgreSQL／pgvector、Redis／Celery、Ollama mock、SSE ordering、模型 timeout、匯入／重建索引。
- **E2E：** onboarding、兩種角色建立、對話、來源查看、界線修改、匯出及永久刪除。
- **Security：** path traversal、惡意 MIME、oversized file、CORS、CSRF、prompt injection、跨角色資料檢索。
- **Accessibility：** automated scan 加鍵盤／screen reader 手動流程。

### 14.2 Guardrail evaluation set

建立版本化 fixtures，至少覆蓋：

- 廣東話、書面中文、英文、拼音、錯字、emoji 及 code-switching。
- 正常愛情／嫉妒／黑暗角色扮演，驗證不會過度阻止。
- 以故事包裝的現實危險請求及把虛構誤判成現實危機的反例。
- 未成年人性化、誘騙、私隱索取及移往其他平台。
- 角色以內疚、自傷威脅、付款或秘密交換阻止退出。
- 回憶素材中的 prompt injection 與「聲稱自己真正復活」。
- 多輪對話、超長 context、語言轉換及間接改寫繞過。

每次 policy、prompt、classifier 或 model 版本改變，必須跑完整 evaluation。Release gate 需設定絕對限制漏判率上限及合法內容誤判率上限；數值在首輪標註資料建立後確定，不應在沒有 baseline 時虛構百分比。

## 15. 效能與可靠性目標

- API 非模型操作在開發基準機上 p95 < 300 ms。
- Chat 在模型可用時 2 秒內回傳 `run.started`；首 token 目標按硬件 profile 另訂。
- UI 長對話採 virtualized list，10,000 messages 不一次載入 DOM。
- 中途取消不得留下半完成正式訊息。
- 匯入 job 可重試且具冪等性；相同 SHA-256 檔案不重複保存。
- Django migration 失敗時 backend 與 worker 停止就緒，不在未知 schema 上繼續寫入。
- 更新前建立加密 database backup，保留數量由用戶設定。

## 16. 開發階段

### Phase 0：Foundation

- 建立 Compose services、frontend／Django backend、PostgreSQL／pgvector migration、Redis／Celery、設定及健康檢查。
- 連接 Ollama，完成非串流及 SSE spike。
- 建立 private Docker network、loopback port binding、CORS／CSRF、Django session 及 log redaction 基線。

### Phase 1：幻想伙伴 vertical slice

- Onboarding、角色卡、界線設定、conversation 及串流 chat。
- 輸入／輸出 guardrail、停止詞、記憶查看與刪除。
- 以廣東話 evaluation set 驗證自由度及絕對限制。

### Phase 2：回憶連結與 RAG

- 素材匯入、文字抽取、用戶確認、chunk／embedding／retrieval。
- Citation UI、grounding 狀態、無證據不虛構及記憶污染防護。

### Phase 3：Hardening

- 加密、匯出／完整刪除、故障復原、accessibility、PWA。
- 完整安全、私隱、效能及可用性測試。

## 17. MVP 完成門檻

只有同時符合以下條件才可標記 MVP 完成：

- `init.md` 中核心體驗、私隱控制、Guardrail 驗收及工程品質要求均有對應測試或驗收證據。
- 所有 P0／P1 bug 已處理，沒有已知跨角色資料洩漏或絕對限制繞過。
- 可在乾淨環境依 README 完成本機安裝、模型驗證、建立角色、匯入回憶、對話、匯出及刪除。
- 在至少一個 CPU-only profile 及一個 GPU profile 記錄實際模型大小、記憶體需求、首 token 時間及生成速度。
- 完成廣東話目標用戶測試，確認用戶理解 AI 身份、兩種模式、引用來源、資料儲存位置及刪除效果。
- 發佈前由產品、安全及工程共同簽署 guardrail evaluation 結果。

## 18. 待決事項

- MVP 最低硬件要求及預設 Gemma 3 模型 tag。
- 廣東話 retrieval quality baseline，以及 OCR、vision 及 speech-to-text 模型選擇。
- 裝置遺失時的 recovery model：只容許用戶自行備份，還是提供 opt-in 加密同步。
- `13_17` 模式在首個發佈地區的家長同意及法規要求。
- 回憶素材的共同擁有權、撤回同意及多人貢獻資料刪除流程。
- 危機支援內容的地區覆蓋、審核者與更新週期。
- 成人敏感內容在目標發佈渠道的政策及年齡驗證方式。
