# -*- coding: utf-8 -*-
"""截屏：全屏截图、压缩、保存、清理旧图。"""

import os, time
import mss
from PIL import Image
from . import config

KEEP_SHOTS = 5


def prune_old(keep=KEEP_SHOTS):
    """只保留最近 keep 张自动命名的截图。

    手动截屏以前走的是 capture()，绕过了清理逻辑，截图会一直堆在
    data/screenshots 里，所以把清理放进 capture() 本身。
    """
    try:
        names = [
            f for f in os.listdir(config.SCREENSHOT_DIR) if f.startswith("screen_") and f.endswith(".jpg")
        ]
    except OSError:
        return
    shots = sorted(
        (os.path.join(config.SCREENSHOT_DIR, f) for f in names), key=os.path.getmtime, reverse=True
    )
    for old in shots[keep:]:
        try:
            os.remove(old)
        except OSError:
            pass


def capture(save_path=None, monitor=0, vision_cfg=None):
    """截取屏幕（默认全部屏幕组合），压缩为 JPEG，返回路径。

    vision_cfg 传进来就直接用，避免每截一张图都 load_config()——
    load_config() 结尾会写盘，等于每次截图都重写一遍 config.json。
    """
    v = vision_cfg if vision_cfg is not None else config.load_config()["vision"]
    with mss.mss() as sct:
        mon = sct.monitors[monitor] if monitor < len(sct.monitors) else sct.monitors[0]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    # 缩放
    max_w = v.get("max_width", 1280)
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
    auto_named = save_path is None
    if auto_named:
        save_path = os.path.join(config.SCREENSHOT_DIR, "screen_" + time.strftime("%Y%m%d_%H%M%S") + ".jpg")
    img.save(save_path, "JPEG", quality=v.get("jpeg_quality", 60))
    if auto_named:
        prune_old()
    return save_path


def latest_or_capture(vision_cfg=None):
    """截取一张新图（主动观察场景使用）。"""
    return capture(vision_cfg=vision_cfg)
