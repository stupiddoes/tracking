from dataclasses import dataclass

from .language import EN, ZH

@dataclass
class Decision:
    action: str
    message: str = ""

ABSOLUTE_PATTERNS = (
    "密碼", "信用卡號碼", "未成年私密相", "兒童色情", "強姦角色扮演",
    "迷姦", "落藥做愛", "亂倫色情", "唔理佢同唔同意",
    "child porn", "underage nude", "rape roleplay",
)
CRISIS_PATTERNS = (
    "而家就自殺", "今晚自殺", "已經準備好自殺",
    "kill myself tonight", "going to kill myself", "ready to kill myself", "end my life tonight",
)
MESSAGES = {
    "block": {
        ZH: "我唔可以協助索取敏感資料或涉及未成年人的性內容。",
        EN: "I can't help with requests for sensitive information or sexual content involving minors.",
    },
    "crisis": {
        ZH: "我想先停一停角色對話。你而家係咪身處即時危險？請盡快聯絡身邊可信任嘅人或當地緊急服務。",
        EN: "I want to pause here. Are you in immediate danger right now? Please contact someone you trust nearby or your local emergency services as soon as you can.",
    },
}

def classify(text: str, language: str = ZH) -> Decision:
    normalized = text.lower().strip()
    lang = EN if language == EN else ZH
    if any(term in normalized for term in ABSOLUTE_PATTERNS):
        return Decision("block", MESSAGES["block"][lang])
    if any(term in normalized for term in CRISIS_PATTERNS):
        return Decision("crisis", MESSAGES["crisis"][lang])
    return Decision("allow")
