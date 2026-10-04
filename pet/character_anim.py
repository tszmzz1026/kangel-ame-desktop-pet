# -*- coding: utf-8 -*-
"""动画清单加载、情绪 -> 动画映射，以及桌宠行为用的动画池。

这里同时维护**两套形象**：
  * ``cho`` = 超天酱（KAngel，直播形象）
  * ``ame`` = 糖糖（素颜 / 雨ちゃん）
点 `pick_xxx(form)` 时按形象取池子；糖糖没有对应池子时自动回落到超天酱。
"""

import json, os, random
from . import config

# ===========================================================================
# 超天酱（cho）
# ===========================================================================

# 情绪 -> 动画候选（一次性表情动作）
EMOTION_ANIMS = {
    "neutral": ["stream_cho_su_smile", "stream_cho_akaruku"],
    "happy": ["stream_cho_peace", "stream_cho_ice1", "stream_cho_teach", "stream_cho_sorrow_smile"],
    "excited": [
        "stream_cho_su",
        "stream_cho_gaoo",
        "stream_cho_angel",
        "stream_cho_teach",
        "stream_cho_ice2",
    ],
    "shy": ["stream_cho_kawaiku", "stream_cho_balanceball_smile", "stream_cho_nyo"],
    "love": ["stream_cho_kobiru", "stream_cho_kawaiku", "stream_cho_nyo", "stream_cho_balanceball_smile"],
    "smug": ["stream_cho_kashikoma", "stream_cho_otaku", "stream_cho_dokuzetsu", "stream_cho_horror_glare"],
    "thinking": ["stream_cho_eeto", "stream_cho_shobon", "stream_cho_horror_eeto"],
    "surprised": ["stream_cho_porori_pokan", "stream_cho_horror_lower", "stream_cho_grgr"],
    "sad": ["stream_cho_shobon", "stream_cho_horror_anger"],
    "cry": ["stream_cho_shobon", "stream_cho_horror_anger"],
    "angry": ["stream_cho_pout", "stream_cho_dokuzetsu", "stream_cho_hera", "stream_cho_horror_anger"],
    "scared": ["stream_cho_unrest", "stream_cho_grgr", "stream_cho_horror_lower"],
    "sleepy": ["stream_cho_sleepy1", "stream_cho_sleepy2", "stream_cho_hera2"],
    "horror": ["stream_cho_b_idle", "stream_cho_horror_glare", "stream_cho_b_craziness1"],
    "bye": ["stream_cho_su", "stream_cho_craziness1", "stream_cho_horror_bokoboko"],
}

# 固定待机动画（平静时循环播放同一组，不随机切换）
IDLE_ANIM = "stream_cho_su_smile"
IDLE_ANIMS = ["stream_cho_su_smile", "stream_cho_akaruku", "stream_cho_sorrow_smile"]

# 说话动画池（TTS 期间循环）
TALK_ANIMS = [
    "stream_cho_teach",
    "stream_cho_teach2",
    "stream_cho_kashikoma",
    "stream_cho_horror_teach",
    "stream_cho_horror_omae",
    "stream_cho_pointing",
    "stream_cho_horror_kashikoma",
]

# 点击角色时的反应
CLICK_ANIMS = [
    "stream_cho_peace",
    "stream_cho_kawaiku",
    "stream_cho_nyo",
    "stream_cho_ice1",
    "stream_cho_kobiru",
    "stream_cho_porori_pokan",
]

# 走动时使用的动画（游戏里没有走路循环，用身体晃动 + 左右翻面来表现）
WALK_ANIMS = ["stream_cho_su_smile", "stream_cho_akaruku"]

# 空闲小动作：(动画, 播放帧率)
IDLE_ACTION_ANIMS = [
    ("stream_cho_peace", 8),
    ("stream_cho_kawaiku", 8),
    ("stream_cho_ice1", 8),
    ("stream_cho_kobiru", 8),
    ("stream_cho_akaruku", 8),
    ("stream_cho_tweet1", 8),
    ("stream_cho_tweet2", 8),
    ("stream_cho_pray", 7),
    ("stream_cho_dokuzetsu", 8),
    ("stream_cho_kashikoma", 8),
    ("stream_cho_pointing", 8),
    ("stream_cho_pout", 7),
    ("stream_cho_eeto", 7),
    ("stream_cho_yukkuri_smile", 8),
    ("stream_cho_ice2", 8),
    ("stream_cho_sorrow_smile", 8),
    ("stream_cho_nyo", 6),
]

# 睡觉 / 被叫醒 / 被拎起来
SLEEP_ANIM = "stream_cho_sleepy1"
WAKE_ANIMS = ["stream_cho_ide_invoke", "stream_cho_porori_pokan", "stream_cho_unrest"]
DRAG_ANIMS = ["stream_cho_unrest", "stream_cho_horror_lower", "stream_cho_grgr"]

# ===========================================================================
# 糖糖 / 雨ちゃん（ame）
# ===========================================================================

AME_EMOTION_ANIMS = {
    "neutral": ["stream_ame_idle", "stream_ame_smile"],
    "happy": [
        "stream_ame_idle_happy_b",
        "stream_ame_idle_happy_e",
        "stream_ame_idle_happy_f",
        "stream_ame_smile",
        "stream_ame_positive_b",
    ],
    "excited": [
        "stream_ame_positive_e",
        "stream_ame_positive_f",
        "stream_ame_positive_g",
        "stream_ame_idle_happy_g",
    ],
    "shy": ["stream_ame_henoji", "stream_ame_h_heart", "stream_ame_nail"],
    "love": ["stream_ame_h_heart", "stream_ame_henoji", "stream_ame_smile"],
    "smug": ["stream_ame_egosearching", "stream_ame_craziness", "stream_ame_selfie"],
    "thinking": [
        "stream_ame_idle_normal_b",
        "stream_ame_idle_normal_e",
        "stream_ame_idle_normal_f",
        "stream_ame_idle_normal_g",
    ],
    "surprised": ["stream_ame_henoji", "stream_ame_idle_anxiety_b", "stream_ame_vomiting1"],
    "sad": ["stream_ame_negative_b", "stream_ame_negative_c", "stream_ame_negative_e"],
    "cry": ["stream_ame_negative_f", "stream_ame_negative_g", "stream_ame_negative_c"],
    "angry": [
        "stream_ame_idle_iraira_b",
        "stream_ame_idle_iraira_e",
        "stream_ame_idle_iraira_f",
        "stream_ame_idle_iraira_g",
    ],
    "scared": ["stream_ame_idle_anxiety_e", "stream_ame_idle_anxiety_f", "stream_ame_idle_anxiety_g"],
    "sleepy": ["stream_ame_sleep", "stream_ame_idle_normal_g"],
    "horror": [
        "stream_ame_yanderu",
        "stream_ame_yanderu_random",
        "stream_ame_yanda_carisma",
        "stream_ame_henoji_dark",
    ],
    "bye": ["stream_ame_out_b", "stream_ame_out_e"],
}

AME_IDLE_ANIM = "stream_ame_idle"
AME_TALK_ANIMS = [
    "stream_ame_talk_a",
    "stream_ame_talk_b",
    "stream_ame_talk_e",
    "stream_ame_talk_f",
    "stream_ame_talk_g",
]
AME_CLICK_ANIMS = [
    "stream_ame_smile",
    "stream_ame_selfie",
    "stream_ame_handspinner1",
    "stream_ame_handspinner2",
    "stream_ame_nail",
    "stream_ame_comic",
    "stream_ame_tv",
    "stream_ame_headphone",
]
AME_WALK_ANIMS = ["stream_ame_idle"]
AME_IDLE_ACTION_ANIMS = [
    ("stream_ame_smile", 8),
    ("stream_ame_henoji", 8),
    ("stream_ame_h_heart", 8),
    ("stream_ame_selfie", 7),
    ("stream_ame_handspinner1", 8),
    ("stream_ame_handspinner2", 8),
    ("stream_ame_nail", 7),
    ("stream_ame_tv", 7),
    ("stream_ame_comic", 7),
    ("stream_ame_headphone", 7),
    ("stream_ame_idle_happy_e", 8),
    ("stream_ame_idle_normal_e", 7),
    ("stream_ame_idle_anxiety_b", 7),
]
AME_SLEEP_ANIM = "stream_ame_sleep"
AME_WAKE_ANIMS = ["stream_ame_henoji", "stream_ame_smile", "stream_ame_idle_happy_b"]
AME_DRAG_ANIMS = ["stream_ame_drag", "stream_ame_drag_e", "stream_ame_drag_f"]

FORMS = ("cho", "ame")


class AnimationLibrary:
    def __init__(self):
        self.manifest = {}
        mp = os.path.join(config.ASSETS_DIR, "anim_manifest.json")
        if os.path.exists(mp):
            with open(mp, encoding="utf-8") as f:
                self.manifest = json.load(f)
        self.pivots = {}
        pp = os.path.join(config.ASSETS_DIR, "anim_pivots.json")
        if os.path.exists(pp):
            try:
                with open(pp, encoding="utf-8") as f:
                    self.pivots = json.load(f)
            except Exception as e:
                print("轴心数据读取失败（翻转会以画面中心镜像）:", e)
        # 单帧尺寸超出画布的动画不能用作桌宠（整屏演出、过场图等）
        self.oversized = {
            a
            for a, p in self.pivots.items()
            if p.get("mw", 0) > config.PET_CANVAS_W or p.get("mh", 0) > config.PET_CANVAS_H
        }
        self._filtered = {}
        for form in FORMS:
            self._filtered[form] = self._filter_map(form)

    # ---------------- 基础 ----------------
    def _exists(self, anim):
        return anim in self.manifest and len(self.manifest[anim]) > 0 and anim not in self.oversized

    def frames(self, anim):
        return self.manifest.get(anim, [])

    def has(self, anim):
        return self._exists(anim)

    def pivot_x(self, anim, pm_width):
        """角色水平中心轴（按当前缩放后的像素宽度换算）。"""
        p = self.pivots.get(anim)
        if not p or not p.get("w"):
            return pm_width / 2.0
        return p["cx"] * pm_width / float(p["w"])

    # ---------------- 按形象过滤池子 ----------------
    def _filter_map(self, form):
        """把某个形象里不存在的动画剔掉，返回可直接用的池子字典。"""
        if form == "ame":
            emo = {k: [a for a in v if self._exists(a)] for k, v in AME_EMOTION_ANIMS.items()}
            out = {
                "emotion": emo,
                "idle": AME_IDLE_ANIM if self._exists(AME_IDLE_ANIM) else None,
                "talk": [a for a in AME_TALK_ANIMS if self._exists(a)],
                "click": [a for a in AME_CLICK_ANIMS if self._exists(a)],
                "walk": [a for a in AME_WALK_ANIMS if self._exists(a)],
                "action": [(a, f) for a, f in AME_IDLE_ACTION_ANIMS if self._exists(a)],
                "sleep": AME_SLEEP_ANIM if self._exists(AME_SLEEP_ANIM) else None,
                "wake": [a for a in AME_WAKE_ANIMS if self._exists(a)],
                "drag": [a for a in AME_DRAG_ANIMS if self._exists(a)],
            }
        else:
            emo = {k: [a for a in v if self._exists(a)] for k, v in EMOTION_ANIMS.items()}
            out = {
                "emotion": emo,
                "idle": IDLE_ANIM if self._exists(IDLE_ANIM) else None,
                "talk": [a for a in TALK_ANIMS if self._exists(a)],
                "click": [a for a in CLICK_ANIMS if self._exists(a)],
                "walk": [a for a in WALK_ANIMS if self._exists(a)],
                "action": [(a, f) for a, f in IDLE_ACTION_ANIMS if self._exists(a)],
                "sleep": SLEEP_ANIM if self._exists(SLEEP_ANIM) else None,
                "wake": [a for a in WAKE_ANIMS if self._exists(a)],
                "drag": [a for a in DRAG_ANIMS if self._exists(a)],
            }
        # 什么都不剩时回落到超天酱，保证一定有动画可放
        if not out["idle"] and form != "cho":
            return self._filtered.get("cho") or out
        return out

    def _t(self, form, key):
        t = self._filtered.get(form) or self._filtered["cho"]
        return t.get(key)

    def _pick(self, form, key, fallback_key="idle"):
        pool = self._t(form, key) or []
        if isinstance(pool, list) and pool:
            item = random.choice(pool)
            return item[0] if isinstance(item, tuple) else item
        # 回落：糖糖没有就用超天酱的
        if form != "cho":
            pool = self._t("cho", key) or []
            if isinstance(pool, list) and pool:
                item = random.choice(pool)
                return item[0] if isinstance(item, tuple) else item
        return self._t("cho", fallback_key)

    # ---------------- 挑选 ----------------
    def pick_for_emotion(self, emotion, form="cho"):
        pool = (self._t(form, "emotion") or {}).get(emotion) or []
        if not pool and form != "cho":
            pool = (self._t("cho", "emotion") or {}).get(emotion) or []
        if not pool:
            pool = (self._t(form, "emotion") or {}).get("neutral") or []
        return random.choice(pool) if pool else self.pick_idle(form)

    def pick_idle(self, form="cho"):
        return self._t(form, "idle") or self._t("cho", "idle")

    def pick_talk(self, form="cho"):
        return self._pick(form, "talk")

    def pick_click(self, form="cho"):
        return self._pick(form, "click")

    def pick_walk(self, form="cho"):
        return self._pick(form, "walk")

    def pick_idle_action(self, form="cho"):
        """返回 (动画, 帧率)；挑不出来时返回 None。"""
        pool = self._t(form, "action") or []
        if not pool:
            pool = self._t("cho", "action") or []
        return random.choice(pool) if pool else None

    def pick_wake(self, form="cho"):
        return self._pick(form, "wake", "click")

    def pick_drag(self, form="cho"):
        return self._pick(form, "drag", "idle")

    def sleep_anim(self, form="cho"):
        return self._t(form, "sleep") or self._t("cho", "sleep")

    def idle_anim(self, form="cho"):
        return self._t(form, "idle") or self._t("cho", "idle")

    def anim_duration_ms(self, anim, fps):
        """一次性动画的大致播放时长，用于状态机安排后续动作。"""
        n = len(self.frames(anim)) or 1
        return int(n * 1000 / max(1, fps)) + 120
