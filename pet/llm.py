# -*- coding: utf-8 -*-
"""LLM 客户端：对话、结构化解析、记忆压缩、视觉输入。同步方法，放在 QThread 中调用。"""

import json, re, base64, threading
from typing import Any
from openai import OpenAI
from . import config
from . import persona
from .memory import Memory

# 模型有时不按英文标签返回，而用日语/中文写情绪，这里统一归一化
EMOTION_ALIASES = {
    # 日语
    "普通": "neutral",
    "平常": "neutral",
    "ニュートラル": "neutral",
    "neutral": "neutral",
    "嬉しい": "happy",
    "うれしい": "happy",
    "楽しい": "happy",
    "喜び": "happy",
    "ハッピー": "happy",
    "笑顔": "happy",
    "笑い": "happy",
    "興奮": "excited",
    "大興奮": "excited",
    "テンション": "excited",
    "わくわく": "excited",
    "恥ずかしい": "shy",
    "照れ": "shy",
    "照れる": "shy",
    "大好き": "love",
    "愛": "love",
    "恋": "love",
    "ラブ": "love",
    "好き": "love",
    "ドヤ顔": "smug",
    "得意": "smug",
    "自信": "smug",
    "誇らしい": "smug",
    "考え中": "thinking",
    "思考": "thinking",
    "迷い": "thinking",
    "考える": "thinking",
    "びっくり": "surprised",
    "驚き": "surprised",
    "驚いた": "surprised",
    "悲しい": "sad",
    "寂しい": "sad",
    "切ない": "sad",
    "落ち込み": "sad",
    "泣き": "cry",
    "涙": "cry",
    "号泣": "cry",
    "泣": "cry",
    "怒り": "angry",
    "怒った": "angry",
    "ムカつく": "angry",
    "ぷんぷん": "angry",
    "怖い": "scared",
    "恐怖": "scared",
    "怯え": "scared",
    "不安": "scared",
    "眠い": "sleepy",
    "眠たい": "sleepy",
    "おやすみ": "sleepy",
    "眠そう": "sleepy",
    "病み": "horror",
    "ホラー": "horror",
    "ヤンデレ": "horror",
    "闇": "horror",
    "バイバイ": "bye",
    "さよなら": "bye",
    "お別れ": "bye",
    "別れ": "bye",
    # 中文
    "中性": "neutral",
    "平静": "neutral",
    "一般": "neutral",
    "开心": "happy",
    "高兴": "happy",
    "快乐": "happy",
    "愉快": "happy",
    "微笑": "happy",
    "兴奋": "excited",
    "激动": "excited",
    "热情": "excited",
    "害羞": "shy",
    "羞涩": "shy",
    "腼腆": "shy",
    "爱": "love",
    "喜欢": "love",
    "恋爱": "love",
    "爱慕": "love",
    "得意": "smug",
    "自满": "smug",
    "骄傲": "smug",
    "自恋": "smug",
    "思考": "thinking",
    "思考中": "thinking",
    "犹豫": "thinking",
    "惊讶": "surprised",
    "吃惊": "surprised",
    "震惊": "surprised",
    "悲伤": "sad",
    "难过": "sad",
    "失落": "sad",
    "寂寞": "sad",
    "哭": "cry",
    "哭泣": "cry",
    "流泪": "cry",
    "大哭": "cry",
    "生气": "angry",
    "愤怒": "angry",
    "恼火": "angry",
    "不满": "angry",
    "害怕": "scared",
    "恐惧": "scared",
    "紧张": "scared",
    "不安": "scared",
    "困": "sleepy",
    "想睡": "sleepy",
    "打瞌睡": "sleepy",
    "黑化": "horror",
    "病娇": "horror",
    "诡异": "horror",
    "阴森": "horror",
    "告别": "bye",
    "再见": "bye",
    "拜拜": "bye",
    "道别": "bye",
}


def normalize_emotion(raw, default="neutral"):
    """把模型返回的情绪（可能是日语/中文/大小写不一）归一化成标准标签。"""
    if not raw:
        return default
    e = str(raw).strip().strip("。.!！~～ 　\"'")
    if not e:
        return default
    low = e.lower()
    if low in persona.EMOTIONS:
        return low
    if e in EMOTION_ALIASES:
        return EMOTION_ALIASES[e]
    # 半个标签（"happy " / "HAPPY!" 之类）
    for tag in persona.EMOTIONS:
        if low == tag or low.startswith(tag):
            return tag
    for alias, tag in EMOTION_ALIASES.items():
        if alias and alias in e:
            return tag
    return default


def parse_reply(raw: str | None) -> dict[str, Any]:
    """从模型输出中解析 JSON 回复。"""
    if not raw:
        return {"emotion": "neutral", "text": "……", "zh": "", "options": []}
    s = raw.strip()
    s = re.sub(r"^```(json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            emotion = normalize_emotion(d.get("emotion"))
            text = d.get("text") or ""
            text = text.strip() if isinstance(text, str) else ""
            zh = d.get("zh") or ""
            zh = zh.strip() if isinstance(zh, str) else ""
            choices = d.get("options", [])
            options = (
                [x.strip() for x in choices if isinstance(x, str) and x.strip()]
                if isinstance(choices, list)
                else []
            )
            return {"emotion": emotion, "text": text or "……", "zh": zh, "options": options[:3]}
        except (ValueError, TypeError, AttributeError):
            pass
    return {"emotion": "neutral", "text": s, "zh": "", "options": []}


def image_to_data_url(path):
    with open(path, "rb") as f:
        b = f.read()
    ext = "jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "png"
    return f"data:image/{ext};base64," + base64.b64encode(b).decode()


class LLMClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.memory = Memory()
        self._client = None
        self._vision_client = None
        # 记录建客户端时用的 (base_url, api_key)：设置里改了就要重建
        self._client_sig = None
        self._vision_sig = None
        self._lock = threading.Lock()

    def _use_vision_client(self, has_image):
        return has_image and bool(self.cfg["llm"].get("vision_base_url"))

    def _client_kwargs(self):
        c = self.cfg["llm"]
        return dict(timeout=float(c.get("timeout", 60)), max_retries=int(c.get("max_retries", 1)))

    def _make_client(self, base_url, api_key):
        return OpenAI(base_url=base_url, api_key=api_key or "dummy", **self._client_kwargs())

    def _get_client(self, for_vision: bool = False) -> OpenAI:
        """取客户端；配置里的接口地址或 Key 变了就自动重建。

        以前这里只判断 `is None`，所以「设置里改好 Key → 还是连不上」，
        必须重启桌宠才生效（换快捷预设同理）。
        """
        c = self.cfg["llm"]
        if for_vision and c.get("vision_base_url"):
            sig = (c["vision_base_url"], c.get("vision_api_key") or c["api_key"] or "")
            signature = (*sig, *self._client_kwargs().values())
            if self._vision_client is None or signature != self._vision_sig:
                self._close(self._vision_client)
                self._vision_client = self._make_client(*sig)
                self._vision_sig = signature
            return self._vision_client
        sig = (c["base_url"], c["api_key"] or "")
        signature = (*sig, *self._client_kwargs().values())
        if self._client is None or signature != self._client_sig:
            self._close(self._client)
            self._client = self._make_client(*sig)
            self._client_sig = signature
        return self._client

    @staticmethod
    def _close(client):
        try:
            if client is not None:
                client.close()
        except Exception:
            pass

    def close(self):
        """退出前关闭 HTTP 连接，避免原生库清理时崩溃。"""
        self._close(self._client)
        self._close(self._vision_client)
        self._client = None
        self._vision_client = None
        self._client_sig = None
        self._vision_sig = None

    def _create(self, client, model, messages, allow_json=True):
        """发起 chat 补全；若模型不支持 json_object 则自动降级为普通模式。"""
        c = self.cfg["llm"]
        common = dict(
            model=model, messages=messages, temperature=c["temperature"], max_tokens=c["max_tokens"]
        )
        if allow_json:
            try:
                return client.chat.completions.create(**common, response_format={"type": "json_object"})
            except Exception as e:
                msg = str(e)
                if any(
                    k in msg
                    for k in ("response_format", "json", "not supported", "Unsupported", "parameter", "400")
                ):
                    pass  # 降级重试
                else:
                    raise
        return client.chat.completions.create(**common)

    def _model(self, has_image):
        c = self.cfg["llm"]
        if has_image and c.get("vision_model"):
            return c["vision_model"]
        return c["model"]

    def _build_messages(self, user_content):
        """按当前记忆拼请求。调用时记忆里**还不该**有这一轮的 user 消息。"""
        sys_text = persona.SYSTEM_PROMPT
        if self.memory.summary:
            sys_text += "\n\n【此前的记忆摘要】\n" + self.memory.summary
        msgs = [{"role": "system", "content": sys_text}]
        msgs.extend(self.memory.recent(self.cfg["memory"]["max_turns"]))
        msgs.append({"role": "user", "content": user_content})
        return msgs

    def _compact_if_needed(self):
        if not self.cfg["memory"]["auto_summary"]:
            return
        if not self.memory.needs_compaction(self.cfg["memory"]["max_turns"]):
            return
        old = self.memory.take_old(self.cfg["memory"]["max_turns"])
        if not old:
            return
        transcript = "\n".join(
            f"{m['role']}: {m['content'] if isinstance(m['content'], str) else '(截图)'}" for m in old
        )
        try:
            client = self._get_client()
            r = client.chat.completions.create(
                model=self.cfg["llm"]["model"],
                messages=[
                    {"role": "system", "content": "你是记忆摘要助手。"},
                    {"role": "user", "content": persona.SUMMARY_PROMPT + "\n\n" + transcript},
                ],
                temperature=0.2,
                max_tokens=500,
            )
            add = r.choices[0].message.content.strip()
            self.memory.summary = (self.memory.summary + "\n" + add).strip()[-3000:]
            self.memory.save()
        except Exception as e:
            # take_old 已经把旧消息摘出来了：失败必须放回去，否则这段历史就永久丢了
            print("记忆压缩失败（已回滚，历史保留）:", e, flush=True)
            self.memory.restore(old)

    def chat(self, text, image_path=None, system_override=None):
        """发送一轮对话，返回解析结果 dict。"""
        with self._lock:
            c = self.cfg["llm"]
            # 未配置视觉模型/地址时，纯文本模型无法识别图片，直接走纯文本避免必失败的请求
            vision_capable = bool(c.get("vision_base_url") or c.get("vision_model"))
            has_image = bool(image_path) and vision_capable
            if has_image:
                url = image_to_data_url(image_path)
                content = [
                    {"type": "text", "text": (system_override or text)},
                    {"type": "image_url", "image_url": {"url": url}},
                ]
            else:
                content = system_override or text
            stored_content = text or "（阿宅君屏幕截图）"

            # 顺序很重要：先按"还没有这一轮"的历史拼消息，再把这句写进记忆。
            # 反过来的话 memory.recent() 里已经含它，末尾又追加一次，模型会收到两遍同一句话。
            messages = self._build_messages(content)
            self.memory.add("user", stored_content)

            last_err = None
            for attempt in range(2):
                try:
                    client = self._get_client(self._use_vision_client(has_image))
                    r = self._create(client, self._model(has_image), messages)
                    raw = r.choices[0].message.content
                    if not raw or not str(raw).strip():
                        # 推理型模型可能把 max_tokens 全花在思考上，正文为空
                        raise RuntimeError(
                            "模型返回了空内容（推理占满了 token），请在设置里把 max_tokens 调大一些"
                        )
                    parsed = parse_reply(raw)
                    self.memory.add("assistant", raw)
                    self._compact_if_needed()
                    return parsed
                except Exception as e:
                    last_err = e
                    # 视觉模型失败：降级为纯文本。只替换最后那条消息，不要重新走一遍记忆。
                    if has_image and attempt == 0:
                        has_image = False
                        messages = messages[:-1] + [
                            {
                                "role": "user",
                                "content": (text or "")
                                + "（截图识别失败，请明确告知无法读取屏幕，不要猜测屏幕内容）",
                            }
                        ]
                        continue
                    break
            self.memory.add("assistant", "……")
            return {"emotion": "sad", "text": f"（连接失败：{last_err}）", "zh": "", "options": []}

    def raw_say(self, prompt, system=None):
        """非对话式调用（用于主动评论等），不写入用户消息。"""
        with self._lock:
            messages = [{"role": "system", "content": system or persona.SYSTEM_PROMPT}]
            messages.extend(self.memory.recent(self.cfg["memory"]["max_turns"]))
            messages.append({"role": "user", "content": prompt})
            try:
                client = self._get_client()
                r = self._create(client, self.cfg["llm"]["model"], messages)
                parsed = parse_reply(r.choices[0].message.content)
                self.memory.add("assistant", r.choices[0].message.content)
                return parsed
            except Exception as e:
                return {"emotion": "sad", "text": f"（连接失败：{e}）", "zh": "", "options": []}
