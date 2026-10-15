import math
import re

_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]")
_WORD = re.compile(r"[A-Za-z0-9_]+")
_SYMBOL = re.compile(
    r"[^\sA-Za-z0-9_\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]"
)


def count_tokens(text: str) -> int:
    """Tokenizer-agnostic estimate, deliberately on the high side for Qwen/BPE vocabularies.

    CJK characters ~1 token each, latin words ~1.3 tokens, punctuation ~0.5.
    """
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    words = len(_WORD.findall(text))
    symbols = len(_SYMBOL.findall(text))
    return math.ceil(cjk + words * 1.3 + symbols * 0.5)
