# -*- coding: utf-8 -*-
"""GPT-SoVITS 语音合成客户端：多音色（超天酱 / 糖糖）、自动启动 API、合成、播放。

音色来自 K&A TTS 的微调模型（GPT + SoVITS 权重 + 参考音频），
每个音色切换时调用 /set_gpt_weights 与 /set_sovits_weights 热加载，
实测每次约 3~4 秒，所以只在音色真正变化时才切。
"""

import os, io, time, subprocess, threading
from collections import OrderedDict
from contextlib import ExitStack
from typing import Any
from urllib.parse import urlparse
import requests, soundfile as sf, sounddevice as sd
from PySide6.QtCore import QObject, Signal

from .textclean import clean_for_tts
from . import config

APP_DIR = config.APP_DIR
REF_DIR = os.path.join(config.RESOURCE_DIR, "voice", "ref")

# 试听用的示例台词（每个音色一句）
DEMO_LINES = {
    "cho": "やっほー、超てんちゃんだよ。今日もずーっと一緒にいようね。",
    "ame": "ふぁ…おはよ…。今日もいっしょにいよ…",
}
DEFAULT_DEMO = "やっほー、超てんちゃんだよ。"


def _first_existing(*paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return paths[0] if paths else ""


class TTSClient(QObject):
    # 跨线程信号：播放开始 / 结束（参数 bool），连接到主线程的动画 slot
    started = Signal()
    finished = Signal(bool)
    voice_changed = Signal(str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.t = cfg["tts"]
        self.base = self.t["api_url"].rstrip("/")
        self.api_proc = None
        self._speaking = False
        self._lock = threading.Lock()
        self._stream = None
        # 合成/换权重串行化，避免两次回复同时切换音色
        self._synth_lock = threading.Lock()
        # 启动 API 也要串行：两个线程同时判断"没起来"会拉起两个 GPT-SoVITS 进程
        self._api_lock = threading.Lock()
        # 播放串行化：保证 started/finished 成对出现、不会交错
        self._play_lock = threading.Lock()
        # 每次朗读领一个编号；编号变了就说明这次朗读已被新的朗读或 stop() 顶掉
        self._gen = 0
        self._gen_lock = threading.Lock()
        # 合成结果缓存：问候语、口头禅、试听台词不用反复合成
        self._wav_cache = OrderedDict()
        self._cache_lock = threading.Lock()
        self.WAV_CACHE_MAX = 40

        self._voices = self._build_voices()
        self._want_voice = self._pick_default_voice()
        self._loaded_voice = None
        self._settings_gen = 0
        self._closed = threading.Event()

    def refresh_config(self) -> None:
        self.stop()
        self._settings_gen += 1
        self.t = self.cfg["tts"]
        self.base = self.t["api_url"].rstrip("/")
        self._voices = self._build_voices()
        self._loaded_voice = None
        with self._cache_lock:
            self._wav_cache.clear()

    def close(self) -> None:
        self._closed.set()
        self.stop()
        process = self.api_proc
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        self.api_proc = None

    # ------------------------------------------------------------------
    # 音色表
    # ------------------------------------------------------------------
    def _resolve(self, p):
        """相对路径按 ka_tts_dir 解析，绝对路径原样返回。"""
        if not p:
            return ""
        p = str(p)
        if os.path.isabs(p) or not self.t.get("ka_tts_dir"):
            return p
        return os.path.normpath(os.path.join(self.t["ka_tts_dir"], p))

    def _build_voices(self):
        out = {}
        for key, m in (self.t.get("models") or {}).items():
            if not isinstance(m, dict):
                continue
            out[key] = {
                "key": key,
                "name": m.get("name") or key,
                "gpt": self._resolve(m.get("gpt_path")),
                "sovits": self._resolve(m.get("sovits_path")),
                "ref": self._resolve(m.get("ref_audio")),
                "prompt": m.get("prompt_text") or "",
                "prompt_lang": m.get("prompt_lang") or "ja",
                "text_lang": m.get("text_lang") or "ja",
            }
        if not out:
            # 兼容最初的扁平配置：只有一个音色
            out["cho"] = {
                "key": "cho",
                "name": "超天酱",
                "gpt": self.t.get("gpt_path", ""),
                "sovits": self.t.get("sovits_path", ""),
                "ref": self._legacy_ref(),
                "prompt": self.t.get("prompt_text", ""),
                "prompt_lang": self.t.get("prompt_lang", "ja"),
                "text_lang": self.t.get("text_lang", "ja"),
            }
        return out

    def _legacy_ref(self):
        ref = self.t.get("ref_audio", "")
        if ref and os.path.exists(ref):
            return ref
        for f in sorted(os.listdir(REF_DIR)) if os.path.isdir(REF_DIR) else []:
            if f.lower().endswith((".wav", ".mp3", ".flac")):
                return os.path.join(REF_DIR, f)
        return _first_existing(os.path.join(APP_DIR, "extracted", "audio", "serihu_sanjou_jp.wav"), ref)

    def _pick_default_voice(self):
        want = self.t.get("default_voice")
        if want in self._voices:
            return want
        return next(iter(self._voices), "cho")

    # ------------------------------------------------------------------
    # 对外：音色
    # ------------------------------------------------------------------
    def voices(self):
        return dict(self._voices)

    def voice_names(self):
        return {k: v["name"] for k, v in self._voices.items()}

    def current_voice(self):
        return self._want_voice

    def set_voice(self, key):
        """切换音色（真正加载权重会推迟到下次说话时）。"""
        if key in self._voices and key != self._want_voice:
            self._want_voice = key
            self.voice_changed.emit(key)
            return True
        return False

    def demo_line(self, key=None):
        key = key or self._want_voice
        return DEMO_LINES.get(key, DEFAULT_DEMO)

    def voice_ready(self, key=None):
        """该音色的权重与参考音频是否齐全。"""
        v = self._voices.get(key or self._want_voice)
        if not v:
            return False
        need = [p for p in (v["gpt"], v["sovits"]) if p]
        return bool(v["ref"] and os.path.exists(v["ref"]) and all(os.path.exists(p) for p in need))

    # ------------------------------------------------------------------
    # API 进程
    # ------------------------------------------------------------------
    def api_ready(self):
        try:
            r = requests.post(self.base + "/tts", json={}, timeout=3)
            # 即使 400 也说明服务在
            return r.status_code in (200, 400, 422)
        except Exception:
            return False

    def _report_api_log(self, log_path, lines=15):
        """把 GPT-SoVITS 的启动日志尾巴写进桌宠日志。

        否则用户只会看到"没声音"，根本不知道原因写在这个文件里
        （pythonw 没有控制台，桌宠的 print 也只在 data/pet.log 里）。
        """
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                tail = [ln for ln in f.read().splitlines() if ln.strip()]
        except OSError:
            return
        if not tail:
            return
        print("---- GPT-SoVITS 启动日志（末尾 %d 行）----" % min(lines, len(tail)), flush=True)
        for ln in tail[-lines:]:
            print("  " + ln, flush=True)
        print("---- 完整日志：%s ----" % log_path, flush=True)

    def start_api(self) -> bool:
        if self._closed.is_set():
            return False
        if self.api_ready():
            return True
        sovits_dir = self.t.get("sovits_dir", "")
        py = os.path.join(sovits_dir, "runtime", "python.exe")
        script = os.path.join(sovits_dir, "api_v2.py")
        if not (os.path.exists(py) and os.path.exists(script)):
            print("未找到 GPT-SoVITS，无法自动启动 TTS API", flush=True)
            return False
        parsed_url = urlparse(self.base)
        if parsed_url.scheme != "http" or parsed_url.hostname not in ("127.0.0.1", "localhost", "::1"):
            print("仅自动启动本机 HTTP TTS 服务", flush=True)
            return False
        log_path = os.path.join(config.DATA_DIR, "tts_api.log")
        # PYTHONIOENCODING=utf-8：api_v2 的日志默认用系统 GBK，遇到 ♡ 之类会 500。
        # 但**绝不能**再加 PYTHONUTF8=1：那会打开 UTF-8 模式，site 模块就会用 UTF-8
        # 去解码 runtime 里按系统编码（中文 Windows 是 GBK）写成的 .pth
        # （例如 Lib\site-packages\users.pth，内容是带中文的路径），于是
        #   Fatal Python error: init_import_site: Failed to import the site module
        #   UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc5 ...
        # 解释器在跑到 api_v2.py 之前就死了 —— 表现就是"完全没有声音"。
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("PYTHONUTF8", None)  # 父进程环境里如果有也一并去掉
        args = [py, "api_v2.py", "-a", parsed_url.hostname, "-p", str(parsed_url.port or 80)]
        cfg_yaml = os.path.join(sovits_dir, "GPT_SoVITS", "configs", "tts_infer.yaml")
        if os.path.exists(cfg_yaml):
            args += ["-c", cfg_yaml]
        try:
            with ExitStack() as stack:
                try:
                    log = stack.enter_context(open(log_path, "w", encoding="utf-8", errors="replace"))
                except OSError:
                    log = subprocess.DEVNULL
                self.api_proc = subprocess.Popen(
                    args,
                    cwd=sovits_dir,
                    stdout=log,
                    stderr=log,
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if self._closed.is_set():
                    self.api_proc.terminate()
                    return False
        except OSError as e:
            print("启动 TTS API 失败:", e, flush=True)
            return False
        # 等待加载（最多 90 秒）；进程要是秒退就没必要干等
        for _ in range(45):
            if self._closed.is_set():
                return False
            if self.api_ready():
                print("TTS API 已就绪", flush=True)
                return True
            if self.api_proc.poll() is not None:
                print(
                    "TTS API 进程已退出（返回码 %s）——这就是没声音的原因" % self.api_proc.returncode,
                    flush=True,
                )
                self._report_api_log(log_path)
                return False
            self._closed.wait(2)
        print("等待 TTS API 超时（90 秒）", flush=True)
        self._report_api_log(log_path)
        return self.api_ready()

    # ------------------------------------------------------------------
    # 权重热加载
    # ------------------------------------------------------------------
    def _ensure_voice(self, key: str) -> dict[str, Any] | None:
        """必要的话把指定音色的权重加载进正在运行的 API。"""
        v = self._voices.get(key) or self._voices.get(self._pick_default_voice())
        if v is None:
            return None
        if self._loaded_voice == v["key"]:
            return v
        self._loaded_voice = None
        settings_gen = self._settings_gen
        for endpoint, label, path in (
            ("set_gpt_weights", "GPT", v["gpt"]),
            ("set_sovits_weights", "SoVITS", v["sovits"]),
        ):
            if not path:
                continue
            if not os.path.exists(path):
                print(f"TTS {label} 权重不存在: {path}")
                return None
            try:
                r = requests.get(f"{self.base}/{endpoint}", params={"weights_path": path}, timeout=300)
                if r.status_code != 200:
                    print(f"{endpoint} 失败:", r.text[:200])
                    return None
                else:
                    print(f"TTS 已加载 {v['name']} 的 {label} 权重", flush=True)
            except requests.RequestException as e:
                print(f"{endpoint} 异常:", e)
                return None
        if settings_gen != self._settings_gen:
            return None
        self._loaded_voice = v["key"]
        return v

    def _ensure_api(self):
        """确保 TTS API 正在运行（没起来就拉起来）。同一时刻只会有一个线程去启动。"""
        with self._api_lock:
            if self._closed.is_set() or not self.t.get("enabled", True):
                return False
            if self.api_ready():
                return True
            if not self.t.get("auto_start_api", True):
                return False
            return self.start_api()

    def preload_voice(self, key: str) -> None:
        """后台预热某个音色（不阻塞界面）。"""
        if self._closed.is_set() or not self.t.get("enabled", True):
            return

        def job() -> None:
            if not self._ensure_api():
                return
            with self._synth_lock:
                self._ensure_voice(key)

        threading.Thread(target=job, daemon=True).start()

    def warmup(self):
        """启动时在后台把 API 拉起来并预热当前音色。

        以前 preload_voice 在 API 未就绪时直接 return，而 API 又是懒启动的，
        于是"提前预热"等于没做：第一句话仍然要等 20~40 秒。
        """

        def job():
            if not self.t.get("enabled", True):
                return
            if not self._ensure_api():
                print("TTS API 未就绪，跳过预热", flush=True)
                return
            with self._synth_lock:
                self._ensure_voice(self._want_voice)
            print("TTS 预热完成:", self._want_voice, flush=True)

        threading.Thread(target=job, daemon=True).start()

    # ------------------------------------------------------------------
    # 合成
    # ------------------------------------------------------------------
    def synthesize(self, text, v):
        payload = {
            "text": text,
            "text_lang": v.get("text_lang", "ja"),
            "ref_audio_path": v["ref"],
            "prompt_text": v.get("prompt", ""),
            "prompt_lang": v.get("prompt_lang", "ja"),
            "text_split_method": "cut5",
            "speed_factor": float(self.t.get("speed", 1.0)),
            "media_type": "wav",
            "streaming_mode": False,
        }
        r = requests.post(self.base + "/tts", json=payload, timeout=180)
        if r.status_code != 200:
            print("TTS 失败:", r.text[:300], flush=True)
            return None
        return r.content

    # ------------------------------------------------------------------
    # 播放
    # ------------------------------------------------------------------
    def stop(self) -> None:
        """取消当前朗读（退出时也会调用）。"""
        with self._gen_lock:
            self._gen += 1  # 编号一变，正在进行的那次朗读就会自己收尾
        with self._lock:
            if self._speaking:
                try:
                    sd.stop()
                except (RuntimeError, sd.PortAudioError):
                    pass
            if self._stream is not None:
                try:
                    self._stream.stop()
                except Exception:
                    pass

    def is_speaking(self):
        with self._lock:
            return self._speaking

    def _cancelled(self, gen):
        with self._gen_lock:
            return gen != self._gen

    # ------------------------------------------------------------------
    # 合成结果缓存（同一句 + 同一音色只合成一次）
    # ------------------------------------------------------------------
    def _cache_key(self, vkey, text):
        return (vkey, round(float(self.t.get("speed", 1.0)), 3), text)

    def _cache_get(self, key):
        with self._cache_lock:
            wav = self._wav_cache.get(key)
            if wav is not None:
                self._wav_cache.move_to_end(key)
            return wav

    def _cache_put(self, key, wav):
        with self._cache_lock:
            self._wav_cache[key] = wav
            self._wav_cache.move_to_end(key)
            while len(self._wav_cache) > self.WAV_CACHE_MAX:
                self._wav_cache.popitem(last=False)

    def _emit_started(self):
        try:
            self.started.emit()
        except RuntimeError:
            pass

    def _emit_finished(self, ok):
        try:
            self.finished.emit(ok)
        except RuntimeError:
            pass

    def speak(self, text, voice=None):
        """后台线程：合成并播放，通过 started/finished 信号通知主线程（线程安全）。"""
        if not self.t.get("enabled", True):
            self._emit_finished(False)
            return
        text = clean_for_tts(text)
        if not text:
            self._emit_finished(False)
            return
        vkey = voice if voice in self._voices else self._want_voice
        with self._gen_lock:
            self._gen += 1
            my_gen = self._gen

        def job():
            if not self._ensure_api():
                print("TTS API 不可用，跳过语音", flush=True)
                self._emit_finished(False)
                return
            if self._cancelled(my_gen):
                self._emit_finished(False)
                return
            key = self._cache_key(vkey, text)
            wav = self._cache_get(key)
            if wav is None:
                with self._synth_lock:
                    if self._cancelled(my_gen):
                        self._emit_finished(False)
                        return
                    v = self._ensure_voice(vkey)
                    if v is None:
                        self._emit_finished(False)
                        return
                    try:
                        wav = self.synthesize(text, v)
                    except (requests.RequestException, ValueError, TypeError) as e:
                        print("TTS 合成失败:", e, flush=True)
                        self._emit_finished(False)
                        return
                if wav is None:
                    self._emit_finished(False)
                    return
                self._cache_put(key, wav)
            if self._cancelled(my_gen):
                self._emit_finished(False)
                return
            try:
                data, sr = sf.read(io.BytesIO(wav), dtype="float32")
            except Exception as e:
                print("音频解码失败:", e, flush=True)
                self._emit_finished(False)
                return
            # 播放段串行化：同一时刻只有一次朗读在响，started/finished 必定成对
            with self._play_lock:
                if self._cancelled(my_gen):
                    self._emit_finished(False)
                    return
                with self._lock:
                    self._speaking = True
                self._emit_started()
                ok = True
                try:
                    self._stream = sd.play(data, sr)
                    total = len(data) / float(sr)
                    waited = 0.0
                    while waited < total and not self._cancelled(my_gen):
                        time.sleep(0.05)
                        waited += 0.05
                    if self._cancelled(my_gen):
                        ok = False
                    else:
                        sd.wait()
                except Exception as e:
                    print("播放失败:", e, flush=True)
                    ok = False
                finally:
                    with self._lock:
                        if self._cancelled(my_gen):
                            sd.stop()
                        self._speaking = False
                        self._stream = None
                    self._emit_finished(ok)

        threading.Thread(target=job, daemon=True).start()
