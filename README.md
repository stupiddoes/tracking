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

語音辨識現時使用瀏覽器 capability，未保證完全離線；正式 local-first STT 將接入 backend worker。回憶 citation 現時是 UI 示範，RAG 素材 pipeline 尚未完成。

設計參考圖：[`design/chat-interface-v1.png`](./design/chat-interface-v1.png)
