# 仍在（Still Here）

Local-first AI 回憶連結與幻想伙伴 Web App。Project 使用獨立、只限 Docker internal network 存取的 Ollama／Gemma 3，React 提供文字對話、語音逐字稿確認及回憶來源介面。

## 啟動

```bash
cp .env.example .env
docker compose up --build
```

首次啟動 Ollama 後，安裝 project 自己的模型：

```bash
docker compose exec ollama ollama pull gemma3:4b
docker compose exec ollama ollama pull embeddinggemma
```

開啟 <http://172.233.65.48:4173>。

Project Ollama 不 publish `11434`，只可由 `ai_private` network 內的 backend／worker 使用。它使用獨立 `ollama_models` volume，不讀取、修改或重啟 server 原有 Ollama。預設不授權 GPU，避免佔用原有 production Ollama 的 VRAM。

## 現階段功能

- Django／DRF 角色及對話 API
- PostgreSQL persistence
- Ollama／Gemma 3 對話
- 基礎輸入 guardrail
- 高保真 mobile chat UI
- Browser 支援時可用廣東話語音轉錄，確認後才送出
- 每位伙伴獨立上載私人回憶相片、描述、日期、標籤及展示規則
- `embeddinggemma` + pgvector 語意檢索；對話可附上經登入權限保護的原相
- 完整對話保存、滾動摘要及舊訊息向量召回，支援長期延續的對話

語音辨識現時使用瀏覽器 capability，未保證完全離線；正式 local-first STT 將接入 backend worker。圖片 RAG 及本機 Vision 自動 caption 已完成；PDF、音訊、影片、OCR 及完整 citation UI 尚待後續版本。

設計參考圖：[`design/chat-interface-v1.png`](./design/chat-interface-v1.png)

技術文件：[`doc/tech_spec.md`](./doc/tech_spec.md) · [`doc/tech_howto.md`](./doc/tech_howto.md)（RAG／pgvector 實作教學）· [`doc/ai_changes.md`](./doc/ai_changes.md)（AI 改動及檔案紀錄）

## 自動部署

Push 到 `main` 後，GitHub Actions 會 SSH 到 production server，在
`/home/virality/tracking` 執行 fast-forward-only pull，再執行
`docker compose up -d --build`。亦可在 Actions 頁面手動觸發。

Repository 需要設定以下 Actions secrets：

- `SSH_HOST`
- `SSH_PORT`
- `SSH_PRIVATE_KEY`
- `SSH_USERNAME`

Server 上的 `.env`、PostgreSQL data、上載資料及項目 Ollama models 均不由
Git 管理，部署時會保留原有 named volumes。項目 Ollama 不 publish host port，
workflow 不會操作 server 原有的 Ollama service。

首次部署若未有 `.env`，workflow 會在 server 上建立權限 `600` 的檔案，並以
`openssl` 產生獨立 PostgreSQL password 及 Django secret。其後部署不會覆蓋
該檔案或更換 credentials。

每次部署會先啟動項目專用 Ollama，確認／下載 8 GB RAM production profile 使用的
`gemma3:4b` 及 `embeddinggemma`，並實際執行一次生成 smoke test，然後才啟動
完整 application stack。模型保存在 production 的 `ollama_models` named volume；
已有模型時 Ollama 只會快速核對 manifest。8 GB host 不建議同時運行 12B 級模型，
需要為 PostgreSQL、Redis、Django、Docker overhead 及 model context 保留記憶體。
