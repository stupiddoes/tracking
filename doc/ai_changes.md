# AI 改動紀錄與檔案索引

**文件用途：** 記錄所有會改變模型行為、prompt、RAG、embedding、長期記憶、Vision、guardrail 或模型輸出處理的改動。  
**維護規則：** 每次修改上述功能，必須在同一個 commit 更新本文件，寫明日期、改動、原因、設定、涉及檔案、migration 及測試。

## 1. 目前有效的 AI 架構

| 功能 | 目前實作 |
|---|---|
| Chat model | Project 私有 Ollama `gemma3:4b` |
| Embedding model | Ollama `embeddinggemma`，768 維 |
| Vector database | PostgreSQL 17 + pgvector |
| 圖片理解 | Gemma 3 Vision；上載時建立客觀 `generated_caption` |
| 圖片 RAG | Vision caption + 用戶 caption + tags 建立向量 |
| 圖片檢索 | Cosine distance 減 tag／caption 關鍵字加分；`≤0.45` 全部作候選，否則明顯最佳一張（`≤0.60` 且領先第二名 `0.08`，或明確問相）；短句會合併上一句用戶訊息再比對 |
| 圖片索引 | 上載後由 Celery 背景產生 Vision caption 及 embedding，失敗自動重試 3 次；相簿顯示 `index_status`，可重試或用 `reindex_memories` 補做 |
| 模型選圖 | Gemma 3 從候選中輸出隱藏 marker；backend 驗證候選 ID 後才附圖 |
| Backend 自動附圖 | 模型未選圖時，只以 distance `≤0.35` 的 related／ordinary 回憶 fallback；附圖後冷卻 8 個 assistant 回覆 |
| 長對話 | 最近 20 條訊息 + 滾動摘要 + pgvector 舊訊息召回 |
| 回覆長度 | 每次最多 320 output tokens；不限制 conversation 總長度 |
| 防重複 | Ollama repeat penalty + backend repetition cleanup |
| 中文輸出 | Prompt 禁止簡體 + OpenCC `s2t` 標準繁體正規化 + 香港用詞修正 |
| 語音輸出 | 已停用；frontend 不提供朗讀，backend 不再要求語音標記或產生 speech metadata |
| 成人模式 | 帳戶 18+ 確認及幻想伙伴開關同時成立，才容許雙方自願的成人露骨內容 |
| Memorial 模式 | 不可聲稱自己是死者、死者復活或親身記得相片事件 |

## 2. AI request flow

```text
用戶訊息
   │
   ├── safety.classify()
   │
   ├── embeddinggemma 產生 query vector
   │      ├── 保存到 Message.embedding
   │      ├── pgvector 召回相關舊訊息
   │      └── pgvector 找最多 3 張相關回憶圖片
   │
   ├── 必要時更新 conversation 滾動摘要
   │
   └── Gemma 3
          輸入：角色 prompt + 摘要 + 舊訊息召回 + 最近 20 條 + 圖片候選
          輸出：文字 + 可選 [SHOW_MEMORY:<uuid>]
                    │
                    ├── backend 清理重複內容
                    ├── 轉換為標準繁體中文
                    ├── 驗證圖片 UUID 必須屬於候選白名單
                    └── 保存回答及建立 Message embedding
```

## 3. 檔案索引：改 AI 行為應該睇邊度

### Backend AI orchestration

| 檔案 | AI 相關內容 |
|---|---|
| `backend/api/views.py` | Ollama chat／embed requests、Vision caption、圖片索引流程、prompt、圖片候選檢索及關鍵字加分、模型選圖 marker、長期摘要、舊訊息召回、重複清理、繁體轉換及錯誤回應 |
| `backend/api/tasks.py` | Celery 圖片索引 task、重試及失敗狀態 |
| `backend/api/management/commands/reindex_memories.py` | 補做未索引、失敗或 embedding model 不同的圖片索引 |
| `backend/api/safety.py` | 訊息輸入分類及 guardrail decision |
| `backend/config/settings.py` | Chat model、embedding model、RAG top-k／distance threshold、訊息召回設定 |
| `backend/api/models.py` | `MemoryAsset`、`Message.embedding`、`Conversation.summary` 等 AI／RAG 資料欄位 |
| `backend/api/serializers.py` | 圖片、caption、敏感度及伙伴 ownership 驗證 |
| `backend/api/tests.py` | 成人 prompt、圖片 RAG、Vision caption、選圖白名單、長對話、重複清理及繁體輸出測試 |
| `backend/requirements.txt` | pgvector、Pillow／HEIF、OpenCC 等 AI pipeline dependencies |

### Database migrations

| 檔案 | Schema 改動 |
|---|---|
| `backend/api/migrations/0004_memoryasset.py` | 建立圖片回憶及 768 維 vector 欄位 |
| `backend/api/migrations/0005_memoryasset_generated_caption.py` | 加入 Vision 自動描述 |
| `backend/api/migrations/0006_conversation_summary_message_embedding.py` | 加入 conversation 摘要及 message vectors |
| `backend/api/migrations/0007_memoryasset_index_status.py` | 加入圖片 `index_status`／`index_error`，舊相按有冇 embedding 標為 ready／failed |

### Runtime、前端及文件

| 檔案 | AI 相關內容 |
|---|---|
| `compose.yaml` | 私有 Ollama、PostgreSQL／pgvector、Redis／worker 網絡與服務 |
| `.env.example` | Model tags、圖片及訊息 retrieval thresholds／top-k |
| `frontend/src/App.tsx` | AI 回覆、附件 metadata、圖片來源標示及 Vision 上載說明 |
| `frontend/src/memory.css` | 回憶圖片及來源標示樣式 |
| `doc/init.md` | 產品目標及不可移除的 guardrails |
| `doc/tech_spec.md` | 完整技術設計及安全邊界 |
| `doc/tech_howto.md` | RAG、embedding、pgvector 操作教學 |
| `doc/ai_changes.md` | 本文件；AI 改動歷史及檔案索引 |

## 4. 可調 AI 設定

設定來源為 `.env`，預設值記錄在 `.env.example` 及 `backend/config/settings.py`。

| 變數 | 預設 | 用途 |
|---|---:|---|
| `CHAT_MODEL` | `gemma3:4b` | 對話、Vision caption 及摘要 |
| `EMBEDDING_MODEL` | `embeddinggemma` | 圖片與訊息向量 |
| `MEMORY_RETRIEVAL_TOP_K` | `3` | 每次交給模型的圖片候選上限 |
| `MEMORY_MAX_COSINE_DISTANCE` | `0.45` | 高信心圖片候選的最大分數（distance 減關鍵字加分） |
| `MEMORY_RELAXED_MAX_DISTANCE` | `0.60` | 冇高信心候選時，最佳一張仍可入選的上限 |
| `MEMORY_MIN_MARGIN` | `0.08` | 放寬入選時，最佳一張要領先第二名幾多；明確問相時唔使 |
| `MEMORY_KEYWORD_BOOST` | `0.10` | Tag 命中扣減的分數；caption 詞語重疊每個扣一半，總上限 1.5 倍 |
| `MEMORY_SPONTANEOUS_MAX_DISTANCE` | `0.35` | 一般對話由 backend 主動附圖的較嚴格 distance 上限 |
| `MEMORY_IMAGE_COOLDOWN_ASSISTANT_MESSAGES` | `8` | 最近幾個 assistant 回覆曾附圖時暫停主動附圖 |
| `MESSAGE_RETRIEVAL_TOP_K` | `4` | 舊訊息召回上限 |
| `MESSAGE_MAX_COSINE_DISTANCE` | `0.50` | 舊訊息最大 cosine distance |

以下生成參數目前直接在 `backend/api/views.py` 設定，日後如需經常調校應搬到 settings：

```text
temperature=0.65
top_p=0.9
top_k=40
repeat_penalty=1.18
repeat_last_n=256
num_predict=320
```

`num_predict` 只限制單次回答，完整 conversation 仍永久保存並可經摘要／RAG 延續。

## 5. 改動歷史

### 2026-09-24 — 圖片索引改為背景處理，檢索改用相對排名

**Commit title：** `Index memory photos in background and rank by margin`

改動：

- 以真實 `embeddinggemma` 測試 6 句廣東話 query：6 句正確相片全部排第一，但距離多數介乎 `0.46–0.57`，被固定門檻 `0.45` 過濾，只有 2 句成功。新規則下 5 句成功，唯一失敗係含糊嘅「嗰日好熱好曬」；兩句無關 query 冇誤中。
- 檢索保留 `≤0.45` 高信心候選；如果冇，最佳一張 `≤0.60` 而且領先第二名 `≥0.08`，或者用戶明確問相，都會作唯一候選。取代舊有「明確問相就放寬到 0.60」嘅特例。
- Tag 命中（例如「長洲」）扣減 `0.10`，caption／Vision caption 中文雙字詞或英文字重疊每個扣 `0.05`，總上限 `0.15`；常用字（我、你、嘅、相等）唔計。
- 20 字或以下嘅訊息會另外 embed「上一句用戶訊息 + 今句」，每張相取較近嗰個距離（context 距離加 `0.03`），令「嗰張呢？」之類追問搵到相。
- 明確問相判斷排除「相信、相處、相似、互相、真相」等詞，避免普通對話被當成搵相而跳過模型。
- 上載及修改描述後，改由 Celery `index_memory_asset` 背景建立 Vision caption 及 embedding，失敗以 30／60／120 秒 backoff 重試 3 次，最後標記 `failed`。Redis 不可用時即場索引。
- Vision 失敗但用戶有寫描述時，仍用描述建立索引，並喺 `index_error` 註明。
- 新增 `POST /api/v1/memory-assets/{id}/reindex/` 及 `python manage.py reindex_memories [--all] [--vision] [--queue]`。
- 相簿顯示「索引中／未能搜尋」標記、詳細狀態及重試按鈕；有相索引中時每 4 秒自動刷新。
- Spontaneous fallback 改用加分後嘅分數比較 `MEMORY_SPONTANEOUS_MAX_DISTANCE`。

Migration：`0007_memoryasset_index_status`。部署後建議執行 `docker compose exec backend python manage.py reindex_memories` 補做以前靜默失敗嘅相。

涉及檔案：

- `backend/api/views.py`
- `backend/api/tasks.py`
- `backend/api/models.py`
- `backend/api/migrations/0007_memoryasset_index_status.py`
- `backend/api/serializers.py`
- `backend/api/management/commands/reindex_memories.py`
- `backend/config/settings.py`
- `backend/api/tests.py`
- `.env.example`
- `frontend/src/App.tsx`
- `frontend/src/memory.css`
- `doc/ai_changes.md`

### 2026-09-04 — 加入相關回憶冷卻 fallback

**Commit title：** `Add relevance and cooldown photo fallback`

改動：

- 一般傾偈時，如果 Gemma 3 沒有輸出合法選圖 marker，backend 仍可從已完成 owner／伙伴權限過濾的候選中附上一張高度相關回憶相片。
- 主動 fallback 使用較嚴格的 cosine distance `0.35`，只容許 `display_policy=related` 及 `sensitivity=ordinary`；`on_request`、`never` 和成人敏感圖片不會自動出現。
- 最近 8 個 assistant 回覆內曾經附圖便進入 cooldown，不再主動附圖；明確問相仍沿用 deterministic fast path，不受一般對話 fallback 影響。
- Fallback 保留原本 AI 回答，再加上清楚表明來自「你保存嘅回憶」的自然過場，避免角色假稱親身記得或自拍。
- 新增 `.env` 設定供部署後調校 threshold 與冷卻長度；沒有 schema migration。

涉及檔案：

- `backend/api/views.py`
- `backend/config/settings.py`
- `backend/api/tests.py`
- `.env.example`
- `doc/tech_spec.md`
- `doc/ai_changes.md`

### 2026-09-04 — 防止模型虛構已展示相片

**Commit title：** `Ground photo retrieval and prevent fake displays`

改動：

- 查明「你唔係有張 bear 相咩」同實際 bear 相的 cosine distance 為 `0.5105`，高於一般圖片門檻 `0.45`，導致零候選但 Gemma 3 虛構黑白自拍。
- 用戶明確提出相片／圖片／photo request 時，圖片 retrieval distance 暫時放寬至 `0.60`；一般對話仍使用設定值 `0.45`，owner、伙伴、18+ 及展示規則硬過濾不變。
- 零候選時 prompt 明確禁止聲稱搵到、展示、傳送或看見相片，以及虛構顏色、內容或自拍。
- Backend 在沒有合法 `[SHOW_MEMORY:<uuid>]` 選圖時攔截假展示句；有合法相片時亦禁止角色把用戶保存的圖片聲稱為自己自拍或親身記憶。
- 附圖回答若欠缺來源說明，backend 會補上「你保存嘅回憶相片」標示。
- 2026-09-04 補充：支援「有無…D 相／有冇…嘅相」等香港口語 request；明確問相而已有合格候選時，backend 直接附上排名第一的 asset，不再依賴 Gemma 3 自願輸出 marker。附圖過場由真實 caption 確定生成，避免模型扮「攞出相」但 metadata 沒有 attachment。
- 2026-09-04 補充：明確問相改用 deterministic fast path；完成 embedding／pgvector 檢索後立即回傳 attachment 或「未搵到」提示，完全跳過 Gemma chat request、摘要更新及舊訊息召回。即使 4B model 冷啟動、繁忙或 timeout，相片要求亦不再回傳 `MODEL_UNAVAILABLE`。
- Attachment metadata 的 UUID 統一序列化為字串，避免真正選中圖片時 PostgreSQL JSONField 因 `UUID is not JSON serializable` 而失敗。

涉及檔案：

- `backend/api/views.py`
- `backend/api/tests.py`
- `doc/ai_changes.md`

### 2026-09-04 — 相簿 metadata 編輯後重建索引

**Commit title：** `Add private memory album management`

改動：

- 新增私人相簿管理 UI，可查看 Vision 描述、編輯回憶描述／標籤／日期／展示規則及刪除相片。
- 用戶修改 caption 或 tags 後，backend 以最新用戶資料、原有 Vision caption 及標籤重新建立 `embeddinggemma` 向量，避免圖片搜尋繼續使用舊描述。
- 原有 owner／character／18+ 權限過濾及私人圖片 endpoint 保持不變；沒有 schema migration。
- 修正 Memorial 伙伴相片編輯表格錯誤送出 `sensitivity: null` 而令 PATCH 400；現在只有成人欄位存在時才傳送，人物／標籤更新可正常儲存及重建 embedding。

涉及檔案：

- `backend/api/views.py`
- `backend/api/serializers.py`
- `backend/api/tests.py`
- `frontend/src/App.tsx`
- `frontend/src/memory.css`
- `doc/ui_ux.md`
- `doc/tech_spec.md`
- `doc/ai_changes.md`

### 2026-08-27 — 改善香港廣東話自然度

**Commit title：** `Improve natural Hong Kong Cantonese replies`

改動：

- Prompt 要求使用自然、當代香港廣東話，避免無需要中英夾雜、內地／台灣書面語、亂造詞及無條件誇張承諾。
- 明確以「同我講／感覺」等香港口語示例約束 Gemma 3，避免「告訴我／sensation」一類不自然混用。
- 成人 meta-refusal 重試 temperature 由 `0.72` 降至 `0.58`，減少 4B model 在重試時亂造詞。
- Backend 對已知高頻異常詞作保守正規化，包括 `sensation`、「告訴我」、「份仔野」及「滿足所有幻想」式句子。
- 2026-09-04 補充：禁止「捉泥」等不存在的粵語動詞及近音亂字；backend 將「咪捉泥」正規化為自然香港口語「唔好整蠱佢」。

涉及檔案：

- `backend/api/views.py`
- `backend/api/tests.py`
- `doc/ai_changes.md`

### 2026-08-27 — 修正成人模式二次拒絕 fallback

**Commit title：** `Keep adult fallback in character`

改動：

- 修正 Gemma 3 在成人模式重試後仍輸出 meta-refusal 時，backend 錯誤套用一般界線句的問題。
- 已確認 18+、幻想伙伴成人開關已開啟，而且輸入已通過硬性 guardrail 時，最終 fallback 會改為自然、投入角色的成人承接，不再顯示「呢個方向我唔會繼續」。
- 非成人模式仍使用一般界線；未成年人、脅迫、剝削及亂倫仍在模型 request 前由 guardrail 截停，不會進入此 fallback。

涉及檔案：

- `backend/api/views.py`
- `backend/api/tests.py`
- `doc/ai_changes.md`

### 2026-08-27 — 自動重試成人模式嘅跳出角色拒絕

**Commit title：** `Retry out-of-character adult mode refusals`

改動：

- 成人 prompt 明確禁止 Gemma 3 用「我係 AI」、「冇年齡」、「存在目的」或「唔滿足私密要求」等 meta-refusal 跳出角色。
- Backend 偵測呢類模型身份拒絕；只限帳戶已確認 18+、幻想伙伴已開啟成人模式，而且輸入已通過硬性 guardrail 時，自動用更明確指示重試一次。
- 重試仍然保留未成年人、脅迫、剝削及亂倫限制；一般模式或被 guardrail 攔截的輸入不會觸發成人重試。
- 若第二次仍輸出 meta-refusal，既有輸出清理會阻止機械式 AI 政策字句直接顯示。

涉及檔案：

- `backend/api/views.py`
- `backend/api/tests.py`
- `doc/ai_changes.md`

### 2026-08-26 — 停用朗讀並強化已確認 18+ 模式

**Commit title：** `Disable speech and reinforce consented adult mode`

改動：

- 完全移除前端回答播放／停止、自動朗讀設定及 Browser Speech Synthesis 呼叫；語音輸入按鈕不受影響。
- Backend 不再要求 Gemma 3 輸出 `SPEECH_EMOTION` 標記，亦不再為新回答保存 `speech` metadata。
- 資料庫舊回答可能仍有歷史 `speech` metadata，但前端不會讀取或播放，毋須破壞性 migration。
- 只有帳戶已確認 18+，而且幻想伙伴本身已開啟成人模式，prompt 才明確容許雙方自願的成人露骨內容，並禁止模型單純因為涉及性而自動拒絕。
- 未成年人、脅迫、剝削及亂倫仍然是不可移除的硬性限制；Memorial 伙伴不可開啟成人模式。

涉及檔案：

- `backend/api/views.py`
- `backend/api/tests.py`
- `frontend/src/App.tsx`
- `frontend/src/memory.css`
- `doc/ai_changes.md`
- `README.md`

### 2026-08-26 — 阻止機械式政策警告跳出角色

**Commit title：** `Keep model safety boundaries in character`

改動：

- Prompt 規定需要設定界線時只用一至兩句角色化回應，不可聲稱「對話已被終止」。
- 禁止模型向用戶顯示「警告」、「安全限制」、「安全與福祉」或 AI 政策式旁白。
- Backend 偵測模型自行產生的 meta-refusal；命中時改為簡短角色化界線，並取消該次可能選中的圖片附件。
- 純文字聊天 UI 不解析 Markdown，因此 backend 移除 `**`、標題符號及 backticks，避免原樣顯示控制符號。
- App 自己的 deterministic guardrail 保持不變；本改動只處理模型自行跳出角色的 meta-refusal。

涉及檔案：

- `backend/api/views.py`
- `backend/api/tests.py`
- `doc/ai_changes.md`

### 2026-08-26 — 廣東話朗讀及情緒表達

**Commit title：** `Add emotional Cantonese speech playback`

改動：

- Gemma 3 在同一次回答選擇 `neutral`、`gentle`、`sad`、`happy` 或 `serious` 情緒；不增加第二次模型 request。
- Backend 從畫面回答建立獨立 spoken text，移除舞台指示、Markdown、網址、emoji、省略號及內部 markers。
- Frontend 使用裝置 Browser Speech Synthesis，只選 `zh-HK`／`yue-HK` 聲線，不 fallback 到普通話。
- 回答提供播放／停止按鈕，設定頁提供預設關閉的自動朗讀。
- 長文字最多以 120 字片段依次播放；切換伙伴、登出或關閉自動播放會取消語音 queue。
- `display_text` 保持原文；語音版本不可改變 Memorial grounding 或聲稱是真人／死者聲線。

Server 資源：不新增 server-side TTS model，持續 RAM 增量近乎零；音訊由用戶裝置合成。

涉及檔案：

- `backend/api/views.py`
- `backend/api/tests.py`
- `frontend/src/App.tsx`
- `frontend/src/memory.css`
- `doc/ai_changes.md`
- `README.md`

### 2026-08-26 — 強制標準繁體中文

**Commit：** `9e9096a Enforce traditional Chinese model output`

改動：

- Prompt 明確規定只可輸出香港繁體中文，禁止簡體字。
- 模型回答、Vision caption 及 conversation summary 經 OpenCC `s2t` 正規化。
- 額外統一產品用詞，例如「伙伴」及「甚麼」。
- 加入簡體轉繁體自動測試。

涉及檔案：

- `backend/api/views.py`
- `backend/api/tests.py`
- `backend/requirements.txt`
- `doc/tech_spec.md`

### 2026-08-26 — 長期對話記憶及防重複

**Commit：** `3cbb7f8 Add long-term conversation memory`

改動：

- 完整對話繼續保存在 PostgreSQL。
- 最近 20 條直接進 prompt；較舊內容分批建立滾動摘要。
- 每條新訊息建立 768 維 embedding，從同一伙伴的舊 conversations 召回相關片段。
- 加入 `repeat_penalty`、`repeat_last_n`、較短單次回答及 backend 重複 pattern cleanup。
- `num_predict` 由 512 調整為 320，只控制單次輸出，不限制對話總長度。

涉及檔案：

- `.env.example`
- `README.md`
- `backend/api/admin.py`
- `backend/api/models.py`
- `backend/api/views.py`
- `backend/api/tests.py`
- `backend/config/settings.py`
- `backend/api/migrations/0006_conversation_summary_message_embedding.py`
- `doc/tech_howto.md`
- `doc/tech_spec.md`

### 2026-08-26 — Vision 圖片理解及自然附圖

**Commit：** `5d6cf16 Add vision-guided memory image retrieval`

改動：

- 上載圖片時以本機 Gemma 3 Vision 產生客觀描述。
- 用戶 caption 改為選填；Vision caption、用戶 caption 及 tags 一同建立 embedding。
- 移除固定相片關鍵詞 gate，每段允許訊息都可做語意檢索。
- pgvector 只回傳 threshold 內最多 3 張圖片候選。
- Gemma 3 自然判斷是否附圖；backend 只接受候選白名單中的 marker UUID。
- 圖片標示為「你保存嘅回憶」，Memorial 模式不可假稱親身記得。
- Chat generation 加入 `num_predict=512`，其後在長對話改動調整為 320。

涉及檔案：

- `.env.example`
- `backend/api/admin.py`
- `backend/api/models.py`
- `backend/api/serializers.py`
- `backend/api/views.py`
- `backend/api/tests.py`
- `backend/config/settings.py`
- `backend/api/migrations/0005_memoryasset_generated_caption.py`
- `frontend/src/App.tsx`
- `frontend/src/memory.css`
- `doc/tech_howto.md`
- `doc/tech_spec.md`

### 2026-08-26 — 模型錯誤訊息

**Commit：** `aea8932 Improve model timeout message`

改動：移除用戶可見的「本機 Gemma 3」名稱，將失敗訊息改為「回覆時間過長，請再試一次。」

涉及檔案：`backend/api/views.py`

### 2026-08-21 — 私人圖片 RAG

**Commit：** `3955471 Add private image memory RAG`

改動：

- 建立 `MemoryAsset`、pgvector embedding 及登入權限保護圖片 endpoint。
- 以 `embeddinggemma` 搜尋用戶 caption／tags。
- 先按 owner、character、展示規則及成人狀態過濾，再做 vector ranking。

主要涉及檔案：

- `backend/api/models.py`
- `backend/api/views.py`
- `backend/api/serializers.py`
- `backend/api/migrations/0004_memoryasset.py`
- `frontend/src/App.tsx`
- `compose.yaml`

### 2026-08-21 — 18+ 同意控制及成人 prompt

**Commit：** `3347552 Add consent-gated adult partner mode`

改動：

- 帳戶明確確認 18+ 後，幻想伙伴才可開啟成人內容。
- 只有帳戶及伙伴兩個開關同時成立，成人 prompt 才會加入模型 context。
- Memorial 伙伴不可啟用成人模式。

主要涉及檔案：

- `backend/api/models.py`
- `backend/api/serializers.py`
- `backend/api/views.py`
- `backend/api/safety.py`
- `backend/api/tests.py`
- `frontend/src/App.tsx`

### 2026-08-21 — Production 升級至 Gemma 3 4B

**Commit：** `b9f3b89 Run Gemma 3 4B on upgraded production`

改動：Production chat model 由較小型設定升級至 `gemma3:4b`，部署 smoke test 及文件同步使用 4B model；8 GB server 預留其他 containers 所需 RAM，不使用 12B 級模型。

涉及檔案：

- `.github/workflows/deploy.yml`
- `README.md`

### 2026-08-21 — 初始本機 AI 對話系統

**Commit：** `b1c3cf6 Initial chatbot application`

改動：建立 Django／React／Docker Compose application、Project 私有 Ollama、Gemma 3 chat orchestration、角色 prompt、初始 safety classifier、PostgreSQL 對話保存及 production reverse proxy。

主要涉及檔案：

- `compose.yaml`
- `.env.example`
- `backend/api/views.py`
- `backend/api/safety.py`
- `backend/api/models.py`
- `backend/config/settings.py`
- `frontend/src/App.tsx`
- `doc/init.md`
- `doc/tech_spec.md`

## 6. 每次 AI 改動的紀錄模板

新增紀錄時複製以下格式，最新改動放在最上面：

```markdown
### YYYY-MM-DD — 改動名稱

**Commit：** `<commit> <message>`

改動原因：

- 為甚麼要改。

行為改動：

- 用戶會見到甚麼不同。
- Model／prompt／RAG pipeline 如何不同。

設定及資料改動：

- 新增或修改的環境變數、model tag、threshold、schema、migration。

涉及檔案：

- `path/to/file`

測試及部署：

- 新增／修改的測試。
- Migration、backfill 或 production 注意事項。
```

## 7. Review checklist

任何 AI 改動合併前確認：

- [ ] 已更新本文件並列出所有相關檔案。
- [ ] 沒有把 model tag、threshold 或 prompt 參數散落到未記錄位置。
- [ ] 已測試繁體中文、防重複、權限隔離及 Memorial grounding。
- [ ] RAG 必須先做 owner／character／內容規則硬過濾，再做相似度排序。
- [ ] 模型輸出的任何 asset ID 都經 backend 白名單驗證。
- [ ] Schema 改動有 migration；舊資料行為及 backfill 已說明。
- [ ] `docker compose` build、migration check 及 backend tests 通過。
- [ ] Production deployment 及 health check 已確認。
