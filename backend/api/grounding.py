"""Rule-based check that archive-mode answers only state details found in the user's own material.

gemma3:4b invents places, foods, dates and quotes about the person even when told not to.
Declarative sentences that mention such a detail absent from the sources are removed;
questions to the user ("例如燒鵝定叉燒呀？") are allowed because they claim nothing.
English replies get equivalent rules for capitalised names, numbers, dishes and quotes.
"""
import re

from .language import EN, ZH

# Characters that turn a place-like match into a generic phrase ("附近啲老茶樓", "嗰間公園").
_GENERIC_PLACE_CHARS = frozenset("我你佢哋嘅個呢嗰啲咗係喺去到同都好一間條座處邊度附近老舊大細新啱例如或者定上落嚟")
_PLACE = re.compile(r"([\u4e00-\u9fff]{1,5})(街市|茶餐廳|茶房|茶室|冰室|餐廳|飯店|麵家|粥店|士多|茶樓|酒樓|酒家|公園|大廈|商場|中心|學校|醫院|教會|街|道|路|區|村|邨|里|灣|山)")
# Hong Kong shop names such as 順記 or 麥奀記, but not 日記／記得.
_SHOP = re.compile(r"(?<![日筆登標印忘牢我你佢唔])([\u4e00-\u9fff]{1,3}?記)(?![得住憶錄者低])")
_NUMBER = re.compile(r"\d{1,4}\s*(?:年|月|日|號|歲|點|蚊|元)")
_QUOTE = re.compile(r"「([^」]{2,})」")
_FOODS = (
    "燒賣", "蝦餃", "叉燒包", "叉燒", "燒鵝", "燒肉", "腸粉", "鳳爪", "糯米雞", "蘿蔔糕", "馬拉糕",
    "蛋撻", "菠蘿包", "雞蛋仔", "魚蛋", "雲吞麵", "雲吞", "牛腩", "車仔麵", "奶茶", "鴛鴦", "檸檬茶",
    "艇仔粥", "皮蛋瘦肉粥", "煲仔飯", "燒味", "白切雞", "豉油雞", "糖水", "紅豆沙", "芝麻糊", "湯圓",
    "月餅", "年糕", "糭", "粽", "餃子", "麵線", "炒飯", "炒麵", "豬扒包", "西多士",
)
# A full stop only ends a sentence before whitespace, so "2.5" and "Mr." inside text stay whole.
_SENTENCE = re.compile(r".+?(?:[。！？!?\n]+|\.(?=\s|$)|$)", re.S)
_FALLBACK = {
    ZH: {
        "note": "呢部分我手上冇資料，唔想亂估；你記得嘅話，可以同我講講。",
        "replaced": "呢樣我手上冇資料，唔想亂估。你記得嘅話，可以同我講講{subject}事嗎？",
    },
    EN: {
        "note": "I don't have that detail in what you've shared, so I won't guess. If you remember, tell me about it.",
        "replaced": "I don't have anything about that yet, so I won't guess. If you remember, would you tell me about {subject}?",
    },
}

# Capitalised words that are not specific details: family titles, festivals, languages, calendar words.
_EN_COMMON = frozenset("""
i i'm i've i'd i'll ai ok okay grandma grandpa granny nana mum mom mother dad father auntie aunt uncle
mama papa christmas easter chinese cantonese english mandarin new year lunar mid-autumn
monday tuesday wednesday thursday friday saturday sunday january february march april may june july
august september october november december
""".split())
_EN_NAME = re.compile(r"(?<![\w'’])[A-Z][A-Za-z'’-]*(?:\s+[A-Z][A-Za-z'’-]*)*")
_EN_NUMBER = re.compile(r"\b(\d{2,4})(?:s|st|nd|rd|th)?\b")
_EN_QUOTE = re.compile(r"[“\"]([^”\"]{6,})[”\"]")
_EN_FOODS = (
    "har gow", "siu mai", "char siu", "cha siu", "egg tart", "milk tea", "wonton", "congee", "roast goose",
    "pineapple bun", "fish ball", "fishball", "rice noodle roll", "cheung fun", "egg waffle", "pork chop bun",
    "claypot rice", "mooncake", "rice dumpling", "turnip cake", "chicken feet", "lo mai gai", "sweet soup",
)


def _is_common(word, name):
    lowered = word.lower()
    return lowered in _EN_COMMON or lowered.rstrip("s") in _EN_COMMON or lowered == name.lower()


def _unsupported_english(text, sources, name):
    text = text.replace("’", "'")
    lowered_sources = sources.lower().replace("’", "'")
    found = []
    for match in _EN_NAME.finditer(text):
        words = [re.sub(r"'s$", "", word) for word in match.group(0).split()]
        if not text[:match.start()].strip():
            words = words[1:]  # Every sentence starts with a capital.
        words = [word for word in words if not _is_common(word, name)]
        if words and not all(word.lower() in lowered_sources for word in words):
            found.append(" ".join(words))
    found.extend(m.group(0) for m in _EN_NUMBER.finditer(text) if m.group(1) not in sources)
    lowered = text.lower()
    found.extend(food for food in _EN_FOODS if food in lowered and food not in lowered_sources)
    speaker = rf"(?:she|he|{re.escape(name)})" if name else "(?:she|he)"
    speech = re.search(
        rf"\b{speaker}\s+(?:always\s+|often\s+|used\s+to\s+|would\s+)?(?:said|say|says|told\s+(?:me|us|you))\b[\s,:]*(.{{8,}})",
        text, re.IGNORECASE,
    )
    if speech and speech.group(1)[:12].lower() not in lowered_sources:
        found.append(speech.group(0)[:30])
    found.extend(m.group(0) for m in _EN_QUOTE.finditer(text) if m.group(1).lower() not in lowered_sources)
    return found


def _unsupported_details(text, sources, name, language=ZH):
    found = _unsupported_english(text, sources, name) if language == EN else []
    for match in _PLACE.finditer(text):
        prefix, core = match.group(1), ""
        while prefix and prefix[-1] not in _GENERIC_PLACE_CHARS:
            core, prefix = prefix[-1] + core, prefix[:-1]
        # Adjacent names merge ("旺角金鳳"); a known trailing name is enough.
        if len(core) >= 2 and not any(core[i:] in sources for i in range(len(core) - 1)):
            found.append(core + match.group(2))
    found.extend(m.group(1) for m in _SHOP.finditer(text) if m.group(1) not in sources)
    found.extend(m.group(0) for m in _NUMBER.finditer(text) if m.group(0).replace(" ", "") not in sources)
    found.extend(food for food in _FOODS if food in text and food not in sources)
    speaker = rf"(?:佢|{re.escape(name)})" if name else "佢"
    speech = re.search(rf"{speaker}(?:以前|成日|經常|常常|都)?話(?!唔定|唔埋|之|你知)(.{{4,}})", text)
    if speech and speech.group(1)[:4] not in sources:
        found.append(f"話{speech.group(1)[:8]}")
    found.extend(m.group(0) for m in _QUOTE.finditer(text) if m.group(1) not in sources)
    return found


# English questions usually open with one of these, and then the whole sentence asks.
_EN_QUESTION_START = re.compile(
    r"^\s*(?:do|does|did|was|were|is|are|am|can|could|would|will|should|have|has|had|what|which|where|when|who|whom|whose|why|how)\b",
    re.IGNORECASE,
)


def _claim_part(sentence):
    """The part of a sentence that asserts something; the final clause of a question only asks."""
    if not re.search(r"[？?]\s*$", sentence):
        return sentence
    if _EN_QUESTION_START.match(sentence):
        return ""
    comma = max(sentence.rfind("，"), sentence.rfind(", "))
    return sentence[:comma] if comma >= 0 else ""


def check_archive_answer(answer, sources, name="", language=ZH):
    """Return (answer, action) where action is "" (unchanged), "trimmed" or "replaced"."""
    kept, removed = [], False
    for sentence in _SENTENCE.findall(answer):
        if _unsupported_details(_claim_part(sentence), sources, name, language):
            removed = True
        else:
            kept.append(sentence)
    if not removed:
        return answer, ""
    fallback = _FALLBACK[EN if language == EN else ZH]
    remaining = "".join(kept).strip()
    if len(remaining) < 6:
        if language == EN:
            subject = name or "them"
        else:
            subject = f"{name}嘅" if name else ""
        return fallback["replaced"].format(subject=subject), "replaced"
    if re.search(r"[？?]\s*$", remaining):
        return remaining, "trimmed"
    return f"{remaining}\n{fallback['note']}", "trimmed"
