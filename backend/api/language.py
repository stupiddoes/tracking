"""Reply language: follow what the user writes, falling back to the album's language.

Hong Kong users mix English words into Cantonese ("有冇 teddy bear 嘅相"), so a message
only counts as English when Latin letters clearly outweigh Chinese characters.
"""
import re

ZH = "zh-HK"
EN = "en"
LANGUAGE_CHOICES = ((ZH, "廣東話"), (EN, "English"))

MESSAGES = {
    "photo_found": {
        ZH: "你保存嘅呢張相，描述係「{caption}」。你睇吓係咪你想搵嗰張？",
        EN: "Here is a photo you saved, described as \"{caption}\". Is this the one you were looking for?",
    },
    "photo_not_found": {
        ZH: "我暫時未喺你保存嘅相簿搵到嗰張相。你可以補充人物、顏色、地點或者日期，我再幫你搵。",
        EN: "I couldn't find that photo in your album yet. Tell me more about the people, colours, place or date and I'll look again.",
    },
    "photo_related": {
        ZH: "講起呢樣，我喺你保存嘅回憶入面搵到一張相關相片：「{caption}」。你睇吓。",
        EN: "That reminds me of a related photo you saved: \"{caption}\". Have a look.",
    },
    "source_label": {ZH: "你保存嘅回憶", EN: "Your saved memory"},
    "meta_refusal": {
        ZH: "呢個方向我唔會繼續。不如轉個大家都舒服嘅方式，我仍然喺度陪你傾。",
        EN: "I'd rather not take this in that direction. Let's try something we're both comfortable with; I'm still here to talk.",
    },
}


def detect_language(text, default=ZH):
    cjk = len(re.findall(r"[㐀-鿿]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if latin >= 3 and latin >= cjk * 3:
        return EN
    if cjk:
        return ZH
    return default if default in (ZH, EN) else ZH


def message(key, language, **values):
    return MESSAGES[key][EN if language == EN else ZH].format(**values)
