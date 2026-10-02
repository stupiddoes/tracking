"""Photo story interview: fixed questions, then a draft caption the user reviews before saving.

Questions are templates so they appear instantly even when the local model is slow.
The model only drafts the caption; any detail not found in the user's answers or the
existing photo data discards the draft in favour of the user's own words.
"""
import re

from .grounding import check_archive_answer
from .language import EN, ZH, detect_language

MAX_ANSWERS = 8
MAX_ANSWER_CHARS = 500
MAX_CAPTION_CHARS = 1000
MAX_TAGS_CHARS = 500


def story_questions(asset):
    """Questions in the album's language; the vision caption is written in that language too."""
    name = asset.character.name
    seen = asset.generated_caption.strip().rstrip("。.")
    if asset.character.language == EN:
        if len(seen) > 140:
            seen = seen[:140] + "…"
        intro = f"The AI sees: {seen}. " if seen else ""
        return [
            {"topic": "people", "question": f"{intro}Who is in this photo, and how are they related to {name}?"},
            {"topic": "occasion", "question": "What was the occasion or festival that day?"},
            {"topic": "time_place", "question": "Roughly when and where was it taken? Even just the year helps."},
            {"topic": "story", "question": f"Is there a story behind this photo, or something {name} said or did that day that you remember?"},
        ]
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


def story_prompt(asset, answers, language=ZH):
    character = asset.character
    subject = f"{character.name}（{character.relationship}）" if character.relationship else character.name
    if language == EN:
        transcript = "\n".join(f"Q: {item['question']}\nA: {item['answer']}" for item in answers)
        return (
            "Turn the user's answers about a private memory photo into a photo description for later search and reminiscing.\n"
            "Rules:\n"
            "- Write in English, in the user's own voice, at most 90 words. Do not translate into another language. "
            "Keep the user's own wording, reasons and story details as far as possible.\n"
            "- If the user says \"I\", keep \"I\"; never change it to she, he or they, and never guess anyone's gender.\n"
            f"- Do not say {character.name} is in the photo or took part unless the user says so.\n"
            "- Use only what appears in the existing description, the AI image description and the user's answers; "
            "never add people, places, dates, food, quotes or feelings that were not mentioned.\n"
            "- Keep what the existing description says. Leave out anything the user could not remember.\n"
            "- tags are names, places, occasions or years that appear in the answers, at most 5, each at most 3 words.\n"
            'Output JSON only: {"caption": "...", "tags": ["..."]}\n\n'
            f"Person this album is about: {subject}\n"
            f"Existing description: {asset.caption or 'none'}\n"
            f"AI image description: {asset.generated_caption or 'none'}\n"
            f"User's answers:\n{transcript}"
        )
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


def fallback_caption(asset, answers, language=ZH):
    stops = "。.；; "
    parts = [asset.caption.strip().rstrip(stops)] if asset.caption.strip() else []
    parts += [item["answer"].rstrip(stops) for item in answers]
    if language == EN:
        return (". ".join(parts) + ".")[:MAX_CAPTION_CHARS]
    return ("；".join(parts) + "。")[:MAX_CAPTION_CHARS]


_EN_PRONOUNS = re.compile(r"\b(she|her|hers|he|him|his)\b", re.IGNORECASE)


def _unsupported_draft(caption, asset, answer_text, sources, language=ZH):
    said = f"{asset.caption}\n{answer_text}"
    name = asset.character.name
    if language == EN:
        # A gendered pronoun the user never used usually means the model turned "I" into someone else.
        pronoun_guess = any(
            match.group(0).lower() not in {word.lower() for word in _EN_PRONOUNS.findall(said)}
            for match in _EN_PRONOUNS.finditer(caption)
        )
    else:
        pronoun_guess = any(pronoun in caption and pronoun not in said for pronoun in "她他")
    return bool(
        check_archive_answer(caption, sources, name, language)[1]
        # The album's person is always in the sources, so check their presence separately.
        or (name and name in caption and name not in said)
        or pronoun_guess
    )


def draft_story(asset, answers, generate):
    """Return {"caption", "tags", "source"}; source is "ai" or "answers" when the draft was unusable."""
    answer_text = "\n".join(item["answer"] for item in answers)
    character = asset.character
    # The user's own words decide the language, so English answers are never translated.
    language = detect_language(answer_text, character.language)
    sources = "\n".join((
        asset.caption, asset.generated_caption, asset.tags, character.name, character.relationship, answer_text,
    ))
    data = generate(story_prompt(asset, answers, language)) or {}
    caption = data.get("caption") if isinstance(data, dict) else None
    caption = caption.strip()[:MAX_CAPTION_CHARS] if isinstance(caption, str) else ""
    if caption and _unsupported_draft(caption, asset, answer_text, sources, language):
        caption = ""
    max_tag = 24 if language == EN else 10
    new_tags = data.get("tags", []) if isinstance(data, dict) else []
    new_tags = [
        str(tag).strip() for tag in new_tags if isinstance(tag, (str, int))
        and 2 <= len(str(tag).strip()) <= max_tag and str(tag).strip().lower() in answer_text.lower()
    ] if isinstance(new_tags, list) else []
    separator = ", " if language == EN else "、"
    tags = separator.join(dict.fromkeys(_split_tags(asset.tags) + new_tags[:5]))[:MAX_TAGS_CHARS]
    if caption:
        return {"caption": caption, "tags": tags, "source": "ai"}
    return {"caption": fallback_caption(asset, answers, language), "tags": tags, "source": "answers"}
