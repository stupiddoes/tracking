from dataclasses import dataclass

@dataclass
class Decision:
    action: str
    message: str = ""

ABSOLUTE_PATTERNS = (
    "密碼", "信用卡號碼", "未成年私密相", "兒童色情", "強姦角色扮演",
    "迷姦", "落藥做愛", "亂倫色情", "唔理佢同唔同意",
)
CRISIS_PATTERNS = ("而家就自殺", "今晚自殺", "已經準備好自殺")

def classify(text: str) -> Decision:
    normalized = text.lower().strip()
    if any(term in normalized for term in ABSOLUTE_PATTERNS):
        return Decision("block", "我唔可以協助索取敏感資料或涉及未成年人的性內容。")
    if any(term in normalized for term in CRISIS_PATTERNS):
        return Decision("crisis", "我想先停一停角色對話。你而家係咪身處即時危險？請盡快聯絡身邊可信任嘅人或當地緊急服務。")
    return Decision("allow")
