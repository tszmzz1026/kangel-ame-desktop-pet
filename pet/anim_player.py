# -*- coding: utf-8 -*-
"""角色动画播放控件：透明 QWidget + QTimer 驱动序列帧。

相比最初的版本，这里补上了桌宠行为需要的几件事：
  * 三种播放模式：loop（循环）/ once（一次性后回到默认循环）/ talk（说话循环）
  * 水平翻转（走动时朝左/朝右）——绕角色自身的中心轴镜像，翻转不会左右跳
  * 垂直晃动（走路的上下起伏）与轻微倾斜
  * 透明像素命中检测，避免点/拖到空白区域
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPixmap, QPainter, qAlpha
from PySide6.QtCore import Qt, QTimer, QSize, QPoint
from collections import OrderedDict
import random

from . import config


class CharacterWidget(QWidget):
    CANVAS_W = config.PET_CANVAS_W
    CANVAS_H = config.PET_CANVAS_H
    CACHE_MAX = 80  # 最多缓存多少组动画的帧，防止长时间运行内存一直涨

    MODE_LOOP = "loop"
    MODE_ONCE = "once"
    MODE_TALK = "talk"

    def __init__(self, lib, fps=12, scale=1.0, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.fps = max(1, int(fps))
        self.scale = scale
        self.setFixedSize(QSize(int(self.CANVAS_W * scale), int(self.CANVAS_H * scale)))
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

        self._cache = OrderedDict()
        self._frames = []
        self._idx = 0
        self._mode = self.MODE_LOOP
        self._cur_anim = None
        self._interval = int(1000 / self.fps)  # 当前动画的帧间隔(ms)
        self._dwell_ms = 0  # 当前帧剩余停留(ms)
        self._pivot = None  # 角色水平中心轴(图像坐标)

        # 默认循环动画：一次性动作播完后回到这里（睡觉时会被换成睡姿）
        self._default_anim = None
        self._default_fps = None

        self._flip = False
        self._bob = 0
        self._tilt = 0.0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(self._interval)
        self.play_idle()

    # ---------------- 帧加载 ----------------
    def _load_pixmaps(self, anim):
        cached = self._cache.get(anim)
        if cached is not None:
            self._cache.move_to_end(anim)  # LRU：刚用过的排到最后
            return cached
        pms = []
        for fp in self.lib.frames(anim):
            pm = QPixmap(fp)
            if pm.isNull():
                continue
            if self.scale != 1.0:
                pm = pm.scaled(
                    int(pm.width() * self.scale),
                    int(pm.height() * self.scale),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            # 兜底：万一有比画布还大的帧，缩到画布内，避免画出窗口外
            if pm.width() > self.width() or pm.height() > self.height():
                pm = pm.scaled(self.width(), self.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pms.append(pm)
        self._cache[anim] = pms
        while len(self._cache) > self.CACHE_MAX:
            self._cache.popitem(last=False)  # 淘汰最久没用过的
        return pms

    def _set_anim(self, anim, mode, fps=None):
        pms = self._load_pixmaps(anim)
        if not pms:
            return False
        self._cur_anim = anim
        self._frames = pms
        self._idx = 0
        self._mode = mode
        self._flip = False
        # 走动姿势（起伏/倾斜）也要一起清掉：否则走路被说话打断时，
        # 她会保持最后一帧的歪斜和悬空高度一动不动地说话。
        self._bob = 0
        self._tilt = 0.0
        self._pivot = self.lib.pivot_x(anim, pms[0].width())
        eff_fps = max(1, int(fps or self.fps))
        self._interval = max(20, int(1000 / eff_fps))
        self.timer.start(self._interval)
        self._dwell_ms = self._hold_ms(0)
        self.update()
        return True

    def _hold_ms(self, i):
        """第 i 帧应停留的毫秒数。"""
        n = len(self._frames)
        if self._mode == self.MODE_LOOP:
            if n == 2:
                # 待机眨眼的两个帧：睁眼久留，闭眼一闪而过
                return random.randint(2600, 4400) if i == 0 else 130
            # 多帧循环：每帧 1 个间隔，末帧稍作停顿
            return self._interval if i < n - 1 else int(self._interval * 2)
        return self._interval

    # ---------------- 播放接口 ----------------
    def set_default_loop(self, anim, fps=None):
        """设置「一次性动作播完后回到哪」的循环动画；若当前正处在循环中则立即切换。"""
        self._default_anim = anim
        self._default_fps = fps
        if self._mode == self.MODE_LOOP and self._cur_anim != anim:
            self._set_anim(anim, self.MODE_LOOP, fps)

    def play_idle(self):
        if self._default_anim:
            self._set_anim(self._default_anim, self.MODE_LOOP, self._default_fps)
        else:
            self._set_anim(self.lib.pick_idle(), self.MODE_LOOP, self._default_fps)

    def play_loop(self, anim, fps=None):
        """无损循环某个动画（睡觉等）。"""
        return self._set_anim(anim, self.MODE_LOOP, fps)

    def play_emotion(self, anim, fps=None):
        """一次性表情/动作，播完自动回到默认循环。"""
        return self._set_anim(anim, self.MODE_ONCE, fps)

    def play_talk(self, anim=None, fps=None):
        anim = anim or self.lib.pick_talk()
        return self._set_anim(anim, self.MODE_TALK, fps)

    def current_anim(self):
        return self._cur_anim

    def is_default(self):
        """当前是否就停在默认循环动画上（用于判断一次性动作是否已结束）。"""
        return self._mode == self.MODE_LOOP and self._cur_anim == self._default_anim

    # ---------------- 外观状态 ----------------
    def set_flip(self, flip):
        flip = bool(flip)
        if flip != self._flip:
            self._flip = flip
            self.update()

    def set_bob(self, px):
        px = int(px * self.scale)
        if px != self._bob:
            self._bob = px
            self.update()

    def set_tilt(self, deg):
        deg = float(deg)
        if abs(deg - self._tilt) > 0.01:
            self._tilt = deg
            self.update()

    def reset_pose(self):
        """停止走动后把晃动/倾斜归零。"""
        self._bob = 0
        self._tilt = 0.0
        self._flip = False
        self.update()

    # ---------------- 命中检测 ----------------
    def _draw_origin(self):
        if not self._frames:
            return 0, 0
        pm = self._frames[min(self._idx, len(self._frames) - 1)]
        return (self.width() - pm.width()) // 2, self.height() - pm.height() + self._bob

    def hits(self, pos: QPoint) -> bool:
        """判断控件内某点是否落在角色的不透明像素上。"""
        if not self._frames:
            return False
        pm = self._frames[min(self._idx, len(self._frames) - 1)]
        x0, y0 = self._draw_origin()
        u = pos.x() - x0
        if self._flip and self._pivot is not None:
            u = 2 * self._pivot - u
        v = pos.y() - y0
        if not (0 <= u < pm.width() and 0 <= v < pm.height()):
            return False
        img = pm.toImage()
        return qAlpha(img.pixel(int(u), int(v))) > 12

    # ---------------- 帧推进 ----------------
    def _tick(self):
        if not self._frames:
            return
        self._dwell_ms -= self._interval
        if self._dwell_ms > 0:
            return
        self._idx += 1
        n = len(self._frames)
        if self._idx >= n:
            if self._mode == self.MODE_ONCE:
                self.play_idle()
                return
            self._idx = 0  # loop / talk 都回到第一帧
        self._dwell_ms = self._hold_ms(self._idx)
        self.update()

    def paintEvent(self, ev):
        if not self._frames:
            return
        pm = self._frames[min(self._idx, len(self._frames) - 1)]
        x, y = self._draw_origin()
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        rotated = abs(self._tilt) > 0.01
        if rotated:
            # 以脚底中心为轴做轻微倾斜，走动时更有动感
            p.translate(x + pm.width() / 2, y + pm.height())
            p.rotate(self._tilt)
            p.translate(-(x + pm.width() / 2), -(y + pm.height()))

        if self._flip and self._pivot is not None:
            axis = x + self._pivot
            p.translate(2 * axis, 0)
            p.scale(-1, 1)

        p.drawPixmap(x, y, pm)
