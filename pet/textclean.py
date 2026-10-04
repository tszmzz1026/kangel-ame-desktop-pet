# -*- coding: utf-8 -*-
"""合成前的文本清洗。

GPT-SoVITS 的 api_v2 内部用 GBK 处理文本，遇到 ♡(U+2661)、♪(U+266A)、
✨(U+2728) 这类字符会直接抛 `'gbk' codec can't encode character` 并返回 400。
而超天酱的人设偏偏满口 ♡☆✨ —— 所以合成前必须先过滤。

规则：
  1. 装饰符号换成停顿（「、」），保留一点语气；
  2. 其余 GBK 编不出来的字符（各种 emoji）直接丢掉；
  3. 去掉括号里的动作描写，那不是台词；
  4. 收拾多余标点与空白。
"""

import re

# 换成停顿更自然
_PAUSE = "♡♥❤💕💖💗💓💞💘❣"
# 直接丢掉
_DROP = "♪♫♬♩☆★✨✧⋆¸¸"

_BRACKETS = re.compile(r"[（(][^）)]*[）)]")


def clean_for_tts(text: str) -> str:
    """把一段台词变成 GPT-SoVITS 能安全处理的文本。"""
    if not text:
        return ""
    t = str(text)
    for ch in _PAUSE:
        t = t.replace(ch, "、")
    for ch in _DROP:
        t = t.replace(ch, "")
    t = _BRACKETS.sub("", t)  # （小声）之类的动作描写不念出来

    # 丢掉所有 GBK 编不出来的字符（emoji 等）
    t = "".join(ch for ch in t if _gbk_ok(ch))

    t = re.sub(r"[、,，]{2,}", "、", t)
    t = re.sub(r"[ \t\u3000]{2,}", " ", t)
    t = re.sub(r"、([。！？!?])", r"\1", t)
    return t.strip(" \t\u3000、,，")


def _gbk_ok(ch: str) -> bool:
    try:
        ch.encode("gbk")
        return True
    except UnicodeEncodeError:
        return False
