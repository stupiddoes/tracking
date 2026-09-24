"""Photo story interview: fixed questions, then a draft caption the user reviews before saving.

Questions are templates so they appear instantly even when the local model is slow.
The model only drafts the caption; any detail not found in the user's answers or the
existing photo data discards the draft in favour of the user's own words.
"""
import re

from .grounding import check_archive_answer

MAX_ANSWERS = 8
MAX_ANSWER_CHARS = 500
MAX_CAPTION_CHARS = 1000
MAX_TAGS_CHARS = 500


def story_questions(asset):
    name = asset.character.name
    seen = asset.generated_caption.strip().rstrip("。")
    if len(seen) > 60:
        seen = seen[:60] + "……"
    intro = f"AI 見到相入面有：{seen}。" if seen else ""
    return [
        {"topic": "people", "question": f"{intro}相入面有邊啲人？佢哋同{name}係咩關係？"},
        {"topic": "occasion", "question": "嗰日係咩場合或者節日？"},
        {"topic": "time_place", "question": "大約係幾時、喺邊度影㗎？記得年份都好。"},
        {"topic": "story", "question": f"呢張相背後有冇啲故事，或者{name}嗰日講過、做過啲咩令你記得？"},
    ]


def clean_answers(raw):
    if not isinstance(raw, list):
        return []
    answers = []
    for item in raw[:MAX_ANSWERS]:
        if not isinstance(item, dict):
            continue
        answer = str(item.get("answer", "")).strip()[:MAX_ANSWER_CHARS]
        if answer:
            answers.append({"question": str(item.get("question", "")).strip()[:200], "answer": answer})
    return answers


def story_prompt(asset, answers):
    character = asset.character
    subject = f"{character.name}（{character.relationship}）" if character.relationship else character.name
    transcript = "\n".join(f"問：{item['question']}\n答：{item['answer']}" for item in answers)
    return (
        "請根據用戶對一張私人回憶相片嘅回答，整理成相片描述，用嚟日後搜尋同回顧。\n"
        "規則：\n"
        "- 用繁體中文，客觀，唔超過150字。盡量保留用戶原話、原因同故事細節。\n"
        "- 用戶自稱「我」就照寫「我」，唔好改成她、他或者佢，亦唔好估任何人嘅性別。\n"
        f"- 除非用戶講明，唔好寫{character.name}喺相入面或者有份參與。\n"
        "- 只可以用下面「原有描述」、「AI 圖片描述」同「用戶回答」入面有嘅資料；"
        "唔可以加入任何冇提過嘅人物、地點、日期、食物、說話或者感受。\n"
        "- 保留原有描述入面嘅資料。用戶答唔記得嘅部分就唔好寫。\n"
        "- tags 係回答入面出現過嘅人名、地點、場合或者年份，最多5個，每個唔超過10字。\n"
        '只輸出 JSON：{"caption": "...", "tags": ["..."]}\n\n'
        f"相簿主角：{subject}\n"
        f"原有描述：{asset.caption or '無'}\n"
        f"AI 圖片描述：{asset.generated_caption or '無'}\n"
        f"用戶回答：\n{transcript}"
    )


def _split_tags(text):
    return [tag.strip() for tag in re.split(r"[,，、;；/\n]+", text) if tag.strip()]


def fallback_caption(asset, answers):
    parts = [asset.caption.strip().rstrip("。")] if asset.caption.strip() else []
    parts += [item["answer"].rstrip("。") for item in answers]
    return ("；".join(parts) + "。")[:MAX_CAPTION_CHARS]


def _unsupported_draft(caption, asset, answer_text, sources):
    said = f"{asset.caption}\n{answer_text}"
    name = asset.character.name
    return bool(
        check_archive_answer(caption, sources, name)[1]
        # The album's person is always in the sources, so check their presence separately.
        or (name and name in caption and name not in said)
        or any(pronoun in caption and pronoun not in said for pronoun in "她他")
    )


def draft_story(asset, answers, generate):
    """Return {"caption", "tags", "source"}; source is "ai" or "answers" when the draft was unusable."""
    answer_text = "\n".join(item["answer"] for item in answers)
    character = asset.character
    sources = "\n".join((
        asset.caption, asset.generated_caption, asset.tags, character.name, character.relationship, answer_text,
    ))
    data = generate(story_prompt(asset, answers)) or {}
    caption = data.get("caption") if isinstance(data, dict) else None
    caption = caption.strip()[:MAX_CAPTION_CHARS] if isinstance(caption, str) else ""
    if caption and _unsupported_draft(caption, asset, answer_text, sources):
        caption = ""
    new_tags = data.get("tags", []) if isinstance(data, dict) else []
    new_tags = [
        str(tag).strip() for tag in new_tags if isinstance(tag, (str, int))
        and 2 <= len(str(tag).strip()) <= 10 and str(tag).strip() in answer_text
    ] if isinstance(new_tags, list) else []
    tags = "、".join(dict.fromkeys(_split_tags(asset.tags) + new_tags[:5]))[:MAX_TAGS_CHARS]
    if caption:
        return {"caption": caption, "tags": tags, "source": "ai"}
    return {"caption": fallback_caption(asset, answers), "tags": tags, "source": "answers"}
