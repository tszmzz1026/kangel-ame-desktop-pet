# -*- coding: utf-8 -*-
"""对话记忆：最近消息 + 长期摘要，本地 JSON 持久化。"""

import copy
import json
import os
import threading
from typing import Any

from . import config
from .storage import write_json


class Memory:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.messages = []
        self.summary = ""
        self._load()

    def _load(self) -> None:
        if os.path.exists(config.MEMORY_PATH):
            try:
                with open(config.MEMORY_PATH, encoding="utf-8") as f:
                    d = json.load(f)
                if not isinstance(d, dict):
                    raise ValueError("记忆根节点必须是 JSON 对象")
                messages = d.get("messages", [])
                self.messages = (
                    [
                        m
                        for m in messages
                        if isinstance(m, dict)
                        and m.get("role") in ("user", "assistant")
                        and isinstance(m.get("content"), str)
                    ]
                    if isinstance(messages, list)
                    else []
                )
                summary = d.get("summary", "")
                self.summary = summary if isinstance(summary, str) else ""
            except (OSError, ValueError, TypeError) as e:
                print("记忆读取失败:", e)

    def save(self) -> None:
        try:
            with self.lock:
                write_json(config.MEMORY_PATH, {"summary": self.summary, "messages": self.messages})
        except (OSError, ValueError, TypeError) as e:
            print("记忆保存失败:", e)

    def add(self, role: str, content: str) -> None:
        with self.lock:
            self.messages.append({"role": role, "content": content})
            self.save()

    def clear(self) -> None:
        with self.lock:
            self.messages = []
            self.summary = ""
            self.save()

    def recent(self, max_turns: int) -> list[dict[str, Any]]:
        """返回最近 max_turns 轮（一对 user/assistant 算一轮）的消息，剥离图片数据。"""
        if max_turns <= 0:
            return []
        with self.lock:
            items = copy.deepcopy(self.messages[-(max_turns * 2) :])
        out = []
        for m in items:
            c = m["content"]
            if isinstance(c, list):
                # 多模态消息：只保留文本，图片替换为占位
                texts = [p.get("text", "") for p in c if p.get("type") == "text"]
                c = "".join(texts)
            out.append({"role": m["role"], "content": c})
        return out

    def needs_compaction(self, max_turns: int) -> bool:
        with self.lock:
            return len(self.messages) > max(1, max_turns) * 2

    def take_old(self, max_turns: int) -> list[dict[str, Any]]:
        """取出超出窗口的旧消息，等待压缩进摘要。"""
        keep = max(1, max_turns) * 2
        with self.lock:
            if len(self.messages) <= keep:
                return []
            old = self.messages[:-keep]
            self.messages = self.messages[-keep:]
            return old

    def restore(self, old: list[dict[str, Any]]) -> None:
        """压缩失败时，把 take_old 摘出去的旧消息原样放回最前面。"""
        if not old:
            return
        with self.lock:
            self.messages = list(old) + self.messages
