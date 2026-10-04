# -*- coding: utf-8 -*-
"""配置管理：读写 data/config.json，首次运行自动生成默认配置并尝试探测 GPT-SoVITS 路径。"""

import copy
import json
import math
import os
import sys
import threading
from typing import Any

from .build_info import TTS_AVAILABLE
from .storage import write_json

FROZEN = getattr(sys, "frozen", False)
APP_DIR = (
    os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
RESOURCE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
DATA_DIR = os.getenv("PET_DATA_DIR") or (
    os.path.join(
        os.getenv("LOCALAPPDATA") or os.path.expanduser("~"),
        "KangelAmePet",
        "tts" if TTS_AVAILABLE else "no_tts",
    )
    if FROZEN
    else os.path.join(APP_DIR, "data")
)
ASSETS_DIR = os.path.join(RESOURCE_DIR, "assets")
_save_lock = threading.Lock()
os.makedirs(DATA_DIR, exist_ok=True)

# 角色画布尺寸：所有能用做桌宠的动画帧都不超过这个尺寸。
# 游戏里少数整屏演出（如 horror_iei / grandend / ame 的 696x454 帧）比画布大，
# 会在 AnimationLibrary 里被自动排除，避免画出窗口外。
PET_CANVAS_W = 360
PET_CANVAS_H = 260

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
MEMORY_PATH = os.path.join(DATA_DIR, "memory.json")
SCREENSHOT_DIR = os.path.join(DATA_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

DEFAULT_CONFIG = {
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": os.getenv("PET_API_KEY", ""),
        "model": "deepseek-flash",
        "vision_model": "deepseek-flash",
        "vision_base_url": "",
        "vision_api_key": "",
        "temperature": 0.9,
        "max_tokens": 1200,
        "timeout": 60,  # 单次请求超时（秒），避免接口卡住时她长时间不理人
        "max_retries": 1,
    },
    "tts": {
        "enabled": True,
        "api_url": os.getenv("TTS_API_URL", "http://127.0.0.1:9880"),
        "auto_start_api": True,
        # GPT-SoVITS 本体（含 runtime\python.exe 与 api_v2.py）
        "sovits_dir": os.getenv("SOVITS_DIR", os.path.join(APP_DIR, "tts_backend", "GPT-SoVITS")),
        # K&A TTS 微调模型根目录；下面 models 里的相对路径都相对它解析
        "ka_tts_dir": os.getenv("KA_TTS_DIR", os.path.join(APP_DIR, "tts_models")),
        "default_voice": "cho",  # 没跟随形象时用哪个音色
        "voice_by_form": True,  # 音色跟随形象：超天酱 / 糖糖
        "speed": 1.0,
        "models": {
            "cho": {
                "name": "超天酱",
                "gpt_path": "models/gptsovits/kangel/kangel_gpt_e22.ckpt",
                "sovits_path": "models/gptsovits/kangel/kangel_sovits_e18.pth",
                "ref_audio": "references/kangel/kangel_reference_010.wav",
                "prompt_text": "超超かわいい絶世の美少女なんだから……超絶最かわてんしちゃん！",
                "prompt_lang": "ja",
                "text_lang": "ja",
            },
            "ame": {
                "name": "糖糖",
                "gpt_path": "models/gptsovits/amechan/amechan_gpt_e24.ckpt",
                "sovits_path": "models/gptsovits/amechan/amechan_sovits_e20.pth",
                "ref_audio": "references/amechan/amechan_reference_068.wav",
                "prompt_text": "本当の幸いってこういう何気ない時間なのかもね。",
                "prompt_lang": "ja",
                "text_lang": "ja",
            },
        },
        # 旧版扁平字段，仅在没有 models 时作为回退
        "ref_audio": os.path.join(APP_DIR, "voice", "ref", "超天酱参考.wav"),
        "prompt_text": "インターネットエンジェル、かわいくさんじゃん！",
        "prompt_lang": "ja",
        "text_lang": "ja",
        "gpt_path": "",
        "sovits_path": "",
    },
    "pet": {
        "scale": 1.0,
        "fps": 12,
        "pos": None,
        "click_animations": True,
    },
    # 桌宠行为：桌面走动、拖拽惯性、空闲小动作、夜间睡觉
    "behavior": {
        "enabled": True,
        "form": "cho",  # 当前形象：cho=超天酱，ame=糖糖（决定待机动画与音色）
        "roaming": True,  # 自己在桌面上走来走去
        "walk_speed": 55,  # 走动速度 px/秒
        "step_rate": 2.2,  # 每秒迈几步（决定上下起伏的频率）
        "bob_px": 4,  # 走动时上下起伏的幅度
        "tilt_deg": 1.2,  # 走动时左右摇摆的角度
        "idle_action": True,  # 空闲时随机做小动作
        "idle_action_min": 20,  # 两次行为之间的最短间隔（秒）
        "idle_action_max": 65,  # 最长间隔（秒）
        "drag_inertia": True,  # 拖拽松手后带惯性飞出
        "drag_follow": 26.0,  # 拖动跟随的弹簧系数（越大越跟手）
        "gravity": 2200,  # 重力加速度 px/秒²
        "throw_bounce": 0.42,  # 落地弹跳系数
        "ground_friction": 0.94,  # 地面摩擦（每 1/60 秒衰减）
        "max_throw_speed": 2400,  # 抛出速度上限
        "sleep_enabled": True,  # 夜间自动睡觉
        "sleep_start": "23:30",
        "sleep_end": "07:00",
        "sleep_form": "ame",  # 睡觉时换成雨ちゃん（素颜）；填 "cho" 则保持超天酱
        "sleep_loop_fps": 4,
    },
    "vision": {
        "enabled": False,
        "interval_minutes": 12,
        "proactive_comment": False,
        "jpeg_quality": 60,
        "max_width": 1280,
    },
    "memory": {
        "max_turns": 24,
        "auto_summary": True,
    },
    "autostart": False,
}


def deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    # 深拷贝：否则用户配置里没写到的段会和 DEFAULT_CONFIG 共享同一个 dict，
    # 运行期写 cfg["pet"]["pos"] 之类的操作会把模块级默认值一起改掉。
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if k in out and isinstance(out[k], dict):
            if isinstance(v, dict):
                out[k] = deep_merge(out[k], v)
        elif k in out and isinstance(out[k], bool):
            if isinstance(v, bool):
                out[k] = v
        elif k in out and isinstance(out[k], str):
            if isinstance(v, str):
                out[k] = v
        elif k in out and isinstance(out[k], (int, float)):
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                out[k] = v
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config() -> dict[str, Any]:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            if not isinstance(user_cfg, dict):
                raise ValueError("配置根节点必须是 JSON 对象")
            cfg = deep_merge(DEFAULT_CONFIG, user_cfg)
        except (OSError, ValueError, TypeError) as e:
            print("配置读取失败，使用默认配置:", e)
    else:
        save_config(cfg)
    for section, key, low, high in (
        ("pet", "scale", 0.25, 3.0),
        ("pet", "fps", 1, 60),
        ("memory", "max_turns", 1, 200),
        ("llm", "timeout", 1, 300),
        ("llm", "max_retries", 0, 5),
        ("vision", "interval_minutes", 2, 180),
    ):
        value = cfg[section][key]
        cfg[section][key] = max(low, min(high, value))
        if isinstance(DEFAULT_CONFIG[section][key], int):
            cfg[section][key] = int(cfg[section][key])
    pos = cfg["pet"].get("pos")
    if not (
        isinstance(pos, list)
        and len(pos) == 2
        and all(isinstance(value, (int, float)) and math.isfinite(value) for value in pos)
    ):
        cfg["pet"]["pos"] = None
    if not TTS_AVAILABLE:
        cfg["tts"]["enabled"] = False
        cfg["tts"]["auto_start_api"] = False
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    try:
        with _save_lock:
            write_json(CONFIG_PATH, cfg)
    except (OSError, ValueError, TypeError) as e:
        print("配置保存失败:", e)


def resource(*parts: str) -> str:
    return os.path.join(ASSETS_DIR, *parts)
