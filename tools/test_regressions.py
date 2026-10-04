# -*- coding: utf-8 -*-
"""本次修复的离线回归测试（不联网、不截屏、不碰 data/memory.json）。

覆盖：
  1. 每轮对话只发一次用户消息（以前 memory.add 在拼消息之前，会重复发送）
  2. 设置里改了接口地址 / API Key 后客户端会重建，不用重启桌宠
  3. 请求超时 / 重试次数按配置生效
  4. 视觉模型失败降级为纯文本时，不会重复用户消息
  5. 记忆压缩失败会把旧消息放回去，不会丢历史
  6. 截图只保留最近几张（手动截屏以前绕过了清理）

运行：.venv\\Scripts\\python.exe tools\\test_regressions.py
"""
import io, os, shutil, sys, time, wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from PySide6.QtCore import QCoreApplication

import numpy as np

import pet.config as config

# 关键：把测试期间的记忆、截图都写到临时目录，别动用户自己的 data/
_TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "test_tmp")
shutil.rmtree(_TMP, ignore_errors=True)
os.makedirs(os.path.join(_TMP, "screenshots"), exist_ok=True)
config.MEMORY_PATH = os.path.join(_TMP, "memory.json")
config.SCREENSHOT_DIR = os.path.join(_TMP, "screenshots")

import pet.vision as vision
from pet.llm import LLMClient

app = QCoreApplication.instance() or QCoreApplication(sys.argv)

FAILURES = []


def check(label, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILURES.append(label)


def make_cfg(**llm_overrides):
    llm = {"base_url": "https://a.example/v1", "api_key": "k1", "model": "m1",
           "vision_model": "", "vision_base_url": "", "vision_api_key": "",
           "temperature": 0.5, "max_tokens": 100, "timeout": 7, "max_retries": 0}
    llm.update(llm_overrides)
    return {"llm": llm, "memory": {"max_turns": 4, "auto_summary": False}}


def fresh_memory(name):
    """每个子测试用独立的记忆文件，互不干扰。"""
    path = os.path.join(_TMP, f"memory_{name}.json")
    if os.path.exists(path):
        os.remove(path)
    config.MEMORY_PATH = path
    return path


def fake_response(text='{"emotion":"happy","text":"やあ","zh":"","options":[]}'):
    inner = type("M", (), {"content": text})()
    return type("R", (), {"choices": [type("O", (), {"message": inner})()]})()


def no_client(*_a, **_k):
    return None


# ---------------------------------------------------------------- 1. 不重复发送
fresh_memory("dup")
cfg = make_cfg()
c = LLMClient(cfg)
seen = {}


def capture_create(client, model, messages, allow_json=True):
    seen["messages"] = messages
    return fake_response()


c._create = capture_create
c._get_client = no_client
c.chat("HELLO")
roles = [m["role"] for m in seen["messages"]]
users = [m for m in seen["messages"] if m["role"] == "user"]
check("请求最后一条是本轮用户消息", roles[-1] == "user", f"roles={roles}")
check("首轮请求只有一条用户消息", len(users) == 1 and users[0]["content"] == "HELLO",
      f"roles={roles} users={[m['content'] for m in users]}")

# 第二轮：记忆里应该正好是 user/assistant/user，不多不少
c.chat("AGAIN")
roles = [m["role"] for m in seen["messages"]]
users = [m for m in seen["messages"] if m["role"] == "user"]
check("第二轮的消息序列正确", roles == ["system", "user", "assistant", "user"],
      f"roles={roles}")
check("第二轮同样只发一次", [m["content"] for m in users] == ["HELLO", "AGAIN"],
      f"users={[m['content'] for m in users]}")

# ---------------------------------------------------------------- 2/3. 客户端重建与超时
fresh_memory("client")
c2 = LLMClient(make_cfg())
cl1 = c2._get_client()
check("超时按配置生效", float(cl1.timeout) == 7, str(cl1.timeout))
check("重试次数按配置生效", int(cl1.max_retries) == 0, str(cl1.max_retries))
check("同一份配置不会重复重建", c2._get_client() is cl1)
c2.cfg["llm"]["api_key"] = "k2"
cl2 = c2._get_client()
check("改了 API Key 会重建客户端", cl2 is not cl1)
c2.cfg["llm"]["base_url"] = "https://b.example/v1"
cl3 = c2._get_client()
check("改了接口地址会重建客户端", cl3 is not cl2)
check("重建后地址是新的", str(cl3.base_url).startswith("https://b.example"), str(cl3.base_url))
c2.close()
check("close() 之后会重新建", c2._get_client() is not cl3)

# 视觉客户端也用同一套判断
c2.cfg["llm"]["vision_base_url"] = "https://v.example/v1"
c2.cfg["llm"]["vision_api_key"] = "vk1"
vc1 = c2._get_client(for_vision=True)
c2.cfg["llm"]["vision_api_key"] = "vk2"
check("视觉客户端跟着视觉 Key 重建", c2._get_client(for_vision=True) is not vc1)

# ---------------------------------------------------------------- 4. 视觉降级
fresh_memory("vision")
c3 = LLMClient(make_cfg(vision_model="vm", vision_base_url="https://v.example/v1"))
calls = []


def flaky_create(client, model, messages, allow_json=True):
    calls.append([dict(m) for m in messages])
    if len(calls) == 1:
        raise RuntimeError("vision boom")
    return fake_response()


c3._create = flaky_create
c3._get_client = no_client
img = os.path.join(_TMP, "fake.png")
with open(img, "wb") as f:
    f.write(b"\x89PNG\r\n\x1a\n")
c3.chat("看看屏幕", image_path=img)
check("带图失败后会重试一次", len(calls) == 2, len(calls))
last_users = [m for m in calls[-1] if m["role"] == "user"]
check("降级后的请求只有一条用户消息", len(last_users) == 1,
      f"{[m['content'] for m in last_users]}")
check("降级后内容变成纯文本", isinstance(last_users[0]["content"], str))
check("第一次请求带的是多模态内容", isinstance(calls[0][-1]["content"], list))
check("降级后记忆里也只有一条本轮消息",
      len([m for m in c3.memory.messages if m["role"] == "user"]) == 1,
      str(c3.memory.messages))

# ---------------------------------------------------------------- 5. 压缩失败不丢历史
fresh_memory("compact_fail")


class _BoomChat:
    class completions:                                    # noqa: N801
        @staticmethod
        def create(**_kw):
            raise RuntimeError("summary boom")


class _BoomClient:
    chat = _BoomChat()


c4 = LLMClient(make_cfg())
for i in range(12):
    c4.memory.add("user", f"u{i}")
    c4.memory.add("assistant", f"a{i}")
snapshot = [(m["role"], m["content"]) for m in c4.memory.messages]
c4.cfg["memory"]["auto_summary"] = True
c4._get_client = lambda *a, **k: _BoomClient()
c4._compact_if_needed()
after = [(m["role"], m["content"]) for m in c4.memory.messages]
check("压缩失败后历史完整回滚", after == snapshot,
      f"{len(snapshot)} -> {len(after)}")
check("压缩失败后最早的消息还在", c4.memory.messages[0]["content"] == "u0",
      str(c4.memory.messages[0]))

# 压缩成功：保留窗口 + 写入摘要
fresh_memory("compact_ok")
c5 = LLMClient(make_cfg())
for i in range(12):
    c5.memory.add("user", f"u{i}")
    c5.memory.add("assistant", f"a{i}")
c5.cfg["memory"]["auto_summary"] = True
c5._get_client = lambda *a, **k: type("C", (), {
    "chat": type("Ch", (), {"completions": type("Co", (), {
        "create": staticmethod(lambda **kw: fake_response("这是摘要"))})()})()})()
c5._compact_if_needed()
check("压缩成功后写入摘要", c5.memory.summary == "这是摘要", repr(c5.memory.summary))
check("压缩成功后只保留最近窗口", len(c5.memory.messages) == 8,
      len(c5.memory.messages))

# ---------------------------------------------------------------- 6. 截图清理
for i in range(8):
    p = os.path.join(config.SCREENSHOT_DIR, f"screen_2026010{i}_120000.jpg")
    with open(p, "wb") as f:
        f.write(b"x")
    os.utime(p, (1000 + i, 1000 + i))
vision.prune_old()
left = sorted(os.listdir(config.SCREENSHOT_DIR))
check("截图只保留最近 5 张", len(left) == 5, len(left))
check("留下的是最新的那几张", left == [f"screen_2026010{i}_120000.jpg" for i in range(3, 8)],
      str(left))
# 非 screen_ 开头的文件不该被删
keep = os.path.join(config.SCREENSHOT_DIR, "keep_me.jpg")
with open(keep, "wb") as f:
    f.write(b"x")
vision.prune_old()
check("不清理非自动命名的文件", os.path.exists(keep))

# ---------------------------------------------------------------- 7. TTS 播放层
print("\n=== TTS 播放（用假的音频设备，不出声）===")
import pet.tts as tts_mod
from pet.tts import TTSClient


def make_wav_bytes(seconds=0.2, sr=8000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.zeros(int(seconds * sr), dtype=np.int16).tobytes())
    return buf.getvalue()


class FakeStream:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class FakeSD:
    def __init__(self):
        self.played = []
        self.waits = 0

    def play(self, data, sr):
        self.played.append((len(data), sr))
        return FakeStream()

    def wait(self):
        self.waits += 1

    def stop(self):
        pass


def wait_until(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    app.processEvents()
    return cond()


fake_sd = FakeSD()
real_sd = tts_mod.sd
tts_mod.sd = fake_sd
try:
    tts = TTSClient(config.load_config())
    tts.api_ready = lambda: True
    tts._ensure_voice = lambda key: {"key": key, "name": key, "ref": "ref.wav",
                                    "text_lang": "ja", "prompt": ""}
    synth_calls = []
    tts.synthesize = lambda text, v: (synth_calls.append(text), make_wav_bytes())[1]

    events = []
    tts.started.connect(lambda: events.append("start"))
    tts.finished.connect(lambda ok: events.append(("finish", ok)))

    tts.speak("テストです")
    wait_until(lambda: any(isinstance(e, tuple) for e in events))
    check("speak 会成对发出 started / finished",
          events[:2] == ["start", ("finish", True)], str(events))
    check("朗读结束后 is_speaking 复位", tts.is_speaking() is False)
    check("确实调用了一次播放", len(fake_sd.played) == 1, str(fake_sd.played))

    n1 = len(synth_calls)
    events.clear()
    tts.speak("テストです")
    wait_until(lambda: any(isinstance(e, tuple) for e in events))
    check("同一句第二次朗读命中缓存，不再合成",
          len(synth_calls) == n1, f"{n1} -> {len(synth_calls)}")
    check("缓存命中后也能正常放完",
          events[:2] == ["start", ("finish", True)], str(events))

    # stop() 取消：播放中按停止
    events.clear()
    tts.synthesize = lambda text, v: make_wav_bytes(3.0)
    tts.speak("長いセリフです")
    wait_until(lambda: "start" in events)
    check("播放中 is_speaking 为 True", tts.is_speaking() is True)
    tts.stop()
    wait_until(lambda: any(isinstance(e, tuple) for e in events))
    check("stop() 后朗读以失败收尾", events[-1] == ("finish", False), str(events))
    check("stop() 后 is_speaking 复位", tts.is_speaking() is False)
    check("stop() 之后的状态不会卡住", tts._cancelled(tts._gen) is False)
finally:
    tts_mod.sd = real_sd

# ---------------------------------------------------------------- 8. 单实例保护
print("\n=== 单实例保护（用独立的套接字名，不干扰真桌宠）===")
from pet.single_instance import SingleInstanceServer, notify_existing

_TEST_NAME = "ChouzetsuTenshiPet-single-test"
shown = []
srv = SingleInstanceServer(lambda: shown.append(1), name=_TEST_NAME)
if srv._server is None:
    print("  [SKIP] 本机建立本地套接字失败，跳过（桌宠里也只会降级为不保护）")
else:
    check("第二次启动能通知到已在运行的实例",
          notify_existing(name=_TEST_NAME) and wait_until(lambda: shown == [1]),
          f"shown={shown}")
    check("再点一次仍然只是让它露个面",
          notify_existing(name=_TEST_NAME) and wait_until(lambda: len(shown) == 2),
          f"shown={shown}")
    srv.close()
    check("关闭后就不再应答", notify_existing(timeout_ms=200, name=_TEST_NAME) is False)

print()
if FAILURES:
    print(f"{len(FAILURES)} 项失败: {FAILURES}")
    sys.exit(1)
print("全部通过 ✔")
