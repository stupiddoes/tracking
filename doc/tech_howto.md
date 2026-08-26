# RAG 與 Vector DB 實作教學

呢份文件用本項目現有程式碼，解釋 RAG、embedding、PostgreSQL／pgvector，以及圖片回憶如何由上載到出現在對話。目標係讀完之後，你可以理解、操作、檢查及逐步改良現有系統。

> 現況提示：目前已實作的是圖片回憶 RAG。系統以本機 Gemma 3 Vision 客觀分析圖片，再把 vision caption、用戶描述及標籤一併轉成向量；`tech_spec.md` 所述的 PDF、音訊、documents／chunks 完整 ingestion pipeline 仍是下一階段設計。

## 1. RAG 是什麼？

RAG 全名是 Retrieval-Augmented Generation，可譯作「檢索增強生成」。它把回答拆成兩件事：

1. **Retrieval（檢索）**：先從私人資料找出與用戶訊息最相關的回憶。
2. **Generation（生成）**：把找到的回憶連同對話交給 Gemma 3，再生成答案。

如果沒有 RAG，chat model 只知道 prompt、近期對話及訓練時學過的通用知識，不會自然知道用戶剛上載的家庭相片。RAG 並不是重新訓練 Gemma 3，而是在每次回答前臨時提供相關資料。

```text
用戶訊息：「記唔記得以前去長洲？」
                  │
                  ▼
       embeddinggemma 產生查詢向量
                  │
                  ▼
 PostgreSQL + pgvector 搜尋最相近的回憶
                  │
                  ▼
 找到：「以前一齊去長洲嘅相；標籤：長洲、家人」
                  │
                  ▼
 連同角色設定及近期對話送入 Gemma 3
                  │
                  ▼
       產生有回憶背景的文字答案及附圖
```

## 2. Vector 與 embedding

### 2.1 Embedding 的直覺

Embedding model 會把一段文字轉成一串浮點數。本項目使用 Ollama 的 `embeddinggemma`，輸出固定 **768 維**向量：

```text
「以前一齊去長洲嘅相」
       ↓ embeddinggemma
[0.012, -0.083, 0.147, ... 共 768 個數值]
```

數字本身不適合由人逐個解讀。重點是語意接近的文字，在向量空間通常也較接近。例如「以前去長洲」與「嗰次長洲旅行」即使字面不同，距離仍可能很近。

Chat model 與 embedding model 有不同工作：

| Model | 輸入／輸出 | 用途 |
|---|---|---|
| `gemma3:4b` | 文字 → 文字 | 理解對話及生成答案 |
| `embeddinggemma` | 文字 → 768 個數字 | 語意搜尋，不負責回答 |

### 2.2 Cosine distance

現有搜尋使用 cosine distance，比較兩個向量的方向。概念上：

```text
cosine similarity 越接近 1 → 語意越相近
cosine distance = 1 - cosine similarity
distance 越小 → 排名越前
```

程式透過 pgvector 的 Django integration 執行：

```python
ranked = assets.exclude(embedding__isnull=True).annotate(
    distance=CosineDistance("embedding", vector)
).order_by("distance")
```

## 3. 點解 Vector DB 用 PostgreSQL + pgvector？

本項目沒有另外部署 Pinecone、Qdrant 或 Chroma，而是在 PostgreSQL 17 安裝 pgvector extension。Compose 使用的 image 是：

```yaml
image: pgvector/pgvector:pg17
```

優點包括：

- 用戶、伙伴、相片 metadata 與 vectors 放在同一個 database。
- 可先用普通 SQL 條件做權限過濾，再做向量排序。
- transaction、backup、migration 及 Django ORM 都沿用同一套工具。
- 現階段資料量不大，不需要多維護一個獨立 vector service。

`MemoryAsset.embedding` 的 Django 欄位是：

```python
embedding = VectorField(dimensions=768, null=True, blank=True)
```

實際 PostgreSQL table 是 `api_memoryasset`，其中 `embedding` 欄位的類型是 `vector(768)`。

## 4. 現有 RAG 流程逐步拆解

### 4.1 上載與建立索引

用戶在介面加入相片時，frontend 以 `multipart/form-data` 呼叫：

```text
POST /api/v1/memory-assets/
```

主要資料包括：

- `character`：屬於哪個伙伴
- `image`：私人原圖
- `caption`：回憶描述，現階段最重要的搜尋內容
- `tags`：人物、地點、事件等關鍵詞
- `captured_at`：拍攝日期
- `display_policy`：何時可以在對話展示
- `sensitivity`：一般或成人內容

Backend 儲存記錄後，把以下文字送到 Ollama：

```python
f"{asset.caption}\n標籤：{asset.tags}"
```

Ollama request 相當於：

```http
POST http://ollama:11434/api/embed
Content-Type: application/json

{
  "model": "embeddinggemma",
  "input": "以前一齊去長洲嘅相\n標籤：長洲, 家人"
}
```

Backend 檢查結果必須剛好有 768 維，然後把 vector 及 model 名稱寫入 `api_memoryasset`。

### 4.2 對話時檢索

每次送出訊息後，系統按以下次序處理：

1. 驗證 conversation 屬於登入用戶。
2. 執行安全分類。
3. 檢查訊息有沒有相片／回憶意圖詞，例如「相」、「圖片」、「記得」、「以前」或 `show me`。
4. 先以 `owner`、`character`、展示規則及 18+ 狀態過濾可用素材。
5. 把用戶訊息轉成 768 維 query vector。
6. 用 cosine distance 排序，只保留 threshold 內最多 3 項候選。
7. 把候選的用戶描述、vision caption、tags、日期及展示規則加入 Gemma 3 system prompt。
8. Gemma 3 判斷圖片是否實質幫助當前對話；如選圖，以隱藏 marker 回傳候選 ID。
9. Backend 移除 marker，並驗證 ID 必須屬於候選白名單。
10. 回覆 metadata 加入受權限保護的圖片 URL，frontend 再用登入 token 讀取原圖及顯示「你保存嘅回憶」。

這個次序非常重要：**權限過濾先於向量排名**。Vector 相似度只負責相關性，不可以用來判斷用戶有沒有權限。

### 4.3 三種展示規則

| `display_policy` | 行為 |
|---|---|
| `on_request` | 用戶明確要求看相片時才可選中 |
| `related` | 對話提到相關回憶時可以主動附圖 |
| `never` | 保存及索引，但不會在對話展示 |

如果 embedding service 暫時失敗，系統不會附圖，但文字對話仍可繼續；它不會隨便 fallback 到最新圖片，以免發出不相關或不應展示的回憶。

### 4.4 長對話記憶

完整訊息會一直保存在 PostgreSQL，不會因單次生成長度而刪除。每次回答使用三層 context：

1. 最近 20 條訊息直接放入 prompt，保留即時語氣及上下文。
2. 較舊訊息分批整理成 conversation 滾動摘要，保留人物、事件、偏好、承諾及未完成話題。
3. 每條新訊息以 `embeddinggemma` 建立 768 維向量；新問題可用 pgvector 從同一伙伴的舊 conversations 召回最多 4 條相關片段。

`num_predict` 只控制單次回答，並不限制整段 conversation。現有回答預設最多 320 output tokens，另使用 `repeat_penalty=1.18` 及 server-side repetition cleanup，避免小模型卡在同一句；下一輪仍可繼續無限延續對話。

```text
完整 PostgreSQL 訊息
   ├── 最近 20 條 ─────────────┐
   ├── 較舊內容滾動摘要 ───────┼──> Gemma 3 回答
   └── pgvector 相關舊片段 ─────┘
```

## 5. 本機操作

### 5.1 啟動及檢查服務

```bash
docker compose up -d
docker compose ps
```

確認 Ollama 有兩個所需模型：

```bash
docker compose exec ollama ollama list
docker compose exec ollama ollama pull gemma3:4b
docker compose exec ollama ollama pull embeddinggemma
```

### 5.2 直接測試 embedding API

Ollama 沒有 publish 到 host，所以從 backend container 呼叫最方便：

```bash
docker compose exec backend python -c '
import httpx
r = httpx.post(
    "http://ollama:11434/api/embed",
    json={"model": "embeddinggemma", "input": "以前去長洲旅行"},
    timeout=60,
)
r.raise_for_status()
v = r.json()["embeddings"][0]
print("dimension:", len(v))
print("first five values:", v[:5])
'
```

預期 `dimension` 是 `768`。如果不是，現有 backend 會拒絕把結果寫入固定的 `vector(768)` 欄位。

### 5.3 查看 pgvector extension 與 schema

```bash
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\\dx vector"'
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\\d api_memoryasset"'
```

以上命令在 PostgreSQL container 內讀取 database user/name；不要把 production 密碼貼到 issue 或 commit。

查看已索引記錄，但避免輸出完整 768 維 vector：

```bash
docker compose exec backend python manage.py shell -c '
from api.models import MemoryAsset
for a in MemoryAsset.objects.all():
    print(a.id, a.caption, a.embedding_model, len(a.embedding) if a.embedding else 0)
'
```

### 5.4 用 Django shell 測試檢索

先找一個角色 ID：

```bash
docker compose exec backend python manage.py shell -c '
from api.models import Character
for c in Character.objects.all(): print(c.id, c.owner_id, c.name)
'
```

再把 `<CHARACTER_UUID>` 換成實際值：

```bash
docker compose exec backend python manage.py shell -c '
from api.models import Character
from api.views import _select_memory_image
c = Character.objects.get(id="<CHARACTER_UUID>")
a = _select_memory_image(c, "記唔記得以前去長洲？")
print(a.id if a else None, a.caption if a else None)
'
```

`_select_memory_image` 是目前的內部 helper，適合學習及除錯；正式整合應經 authenticated API，而不是把它當成穩定 public API。

## 6. 如何寫出容易被搜尋到的回憶

現階段 embedding 會讀 vision caption、用戶 caption 及 tags。Vision 只能描述可見內容，通常不知道人物身份、準確地點及相片背後故事，所以用戶補充資料仍然十分重要。

較弱：

```text
caption: 一張相
tags: 媽媽
```

較好：

```text
caption: 2022 年媽媽生日，我哋喺長洲海旁食蛋糕，當日落住微雨
tags: 媽媽, 生日, 長洲, 海旁, 蛋糕, 2022
captured_at: 2022-06-18
```

建議 caption 包含「人物、事件、地點、時間、感受」中最相關的資料，但不要虛構不知道的細節。Tags 適合放別名、舊稱及容易出現在問題中的詞。

## 7. 常見問題與除錯

### 上載成功，但 `embedding` 是空值

現有 `perform_create` 會在 Ollama embedding 失敗時保留相片，但不阻止上載。依次檢查：

```bash
docker compose ps
docker compose logs --tail=200 backend ollama
docker compose exec ollama ollama list
```

常見原因是 `embeddinggemma` 未下載、Ollama 未 ready、request timeout，或模型輸出維度與 768 不符。

### 明明有相片，但對話沒有召回

檢查：

- 訊息有沒有回憶／圖片意圖詞。
- `display_policy` 是否為 `never`。
- 非明確要求相片時，素材是否設為 `related`。
- 素材與 conversation 是否屬於同一個 `owner` 及 `character`。
- 成人素材是否同時通過帳戶 18+ 確認及伙伴成人內容開關。
- `embedding` 是否存在。

### 結果相關性不好

先改善 caption／tags，再考慮演算法。現有版本預設 `MEMORY_MAX_COSINE_DISTANCE=0.45`，並最多取 `MEMORY_RETRIEVAL_TOP_K=3`。這是安全起點，不是永久最佳值；資料增多後，應記錄距離分布，再以真實測試集調整，而不是隨意猜數值。

### 更新 embedding model 後出錯

`VectorField(dimensions=768)` 不接受其他維度。不要把不同 model／維度混在同一欄位。正確做法是：

1. 決定新 model 與固定版本。
2. 建立新欄位或新 embedding table/version。
3. 背景重建所有 vectors。
4. 驗證搜尋質素後才切換讀取。
5. 最後才清理舊 index。

## 8. 私隱與安全設計

- 每次 queryset 都以 `request.user` 或 `character.owner` 作硬性 owner filter。
- 圖片不透過公開 media URL 提供，只可經 authenticated content endpoint 讀取。
- Vector 不是安全邊界；即使 vector 沒有原文，也不應視為匿名或可公開資料。
- 刪除素材時同時刪除 database row 及儲存檔案。
- `never` 是展示規則，不等於不建立 embedding；如果用戶要求完全不索引，需要另加明確的 indexing opt-out。
- Memorial 模式只可把素材當成用戶保存的資料，模型不可聲稱自己真正記得或就是死者本人。

## 9. 現有版本的限制

目前實作簡單而可運作，但仍有以下限制：

- 已有 vision caption，但沒有 OCR、PDF 或音訊轉錄；模型亦不能可靠辨認人物身份。
- Top-k 候選目前最多 3 張，但每次回覆最多只展示一張。
- 已有 similarity threshold，但仍沒有 retrieval score logging 或 citation table。
- 上載時同步建立 embedding；大量檔案應改由 Celery job 處理。
- Embedding 失敗後沒有自動 retry／re-index queue。
- 尚未建立 HNSW index；小型資料庫用 exact search 合理，數量增長後才應 benchmark。
- 每段允許的訊息都會做 embedding retrieval，資料量及流量增加後要加入 cache／metrics 評估成本。

## 10. 建議學習及改良次序

1. **觀察 vectors**：用相似及不相似句子產生 embedding，比較 cosine distance。
2. **建立小型評測集**：準備約 20 個回憶及 30 條問題，標記每題應召回哪項。
3. **加入 score logging**：記錄 top results 及 distance，不記錄不必要的私人原文。
4. **調校 threshold／top-k**：用評測結果調整現有預設值，不靠直覺。
5. **抽出 RAG service**：把 embedding、filter、ranking、fallback 從 `views.py` 移到獨立 service。
6. **非同步 indexing**：由 Celery 建立及重建 embeddings，顯示 processing 狀態。
7. **完整 ingestion**：加入 documents、chunks、OCR、PDF text extraction 及音訊 transcript。
8. **建立 citations**：讓每段回答可指出用了哪個回憶來源。
9. **資料量足夠才測 HNSW**：比較 recall、latency、RAM 及寫入成本後再建立 index。

## 11. 對照程式碼

| 主題 | 檔案 |
|---|---|
| Vector model 欄位 | `backend/api/models.py` 的 `MemoryAsset` |
| pgvector migration | `backend/api/migrations/0004_memoryasset.py` |
| 建立 embedding | `backend/api/views.py` 的 `_embedding`、`perform_create` |
| 權限及相似度搜尋 | `backend/api/views.py` 的 `_select_memory_image` |
| RAG context 加入 prompt | `backend/api/views.py` 的 `_prompt`、`send_message` |
| 上載驗證 | `backend/api/serializers.py` 的 `MemoryAssetSerializer` |
| API routes | `backend/api/urls.py` |
| 自動化測試 | `backend/api/tests.py` 的 `MemoryAssetTests` |
| Model／DB Compose 設定 | `compose.yaml`、`.env.example` |
| 未來完整設計 | `doc/tech_spec.md` 的回憶素材與向量章節 |

## 12. 一句總結

這個項目的 RAG，就是先把每段私人回憶描述變成 768 維 vector 存入 pgvector；對話時把問題變成同類 vector，在通過 owner、伙伴及內容規則後找出最相近回憶，再把文字證據和私人圖片交給 Gemma 3 生成更貼近用戶背景的回答。
