# -*- coding: utf-8 -*-
"""桌宠行为引擎：桌面走动、拖拽惯性、空闲小动作、夜间睡觉。

设计要点
--------
* 一个 ~60Hz 的定时器推进状态机，位移用浮点积分，避免整数取整造成的抖动。
* 引擎不直接操作窗口，只发出 `moved` 信号；动画则直接驱动 CharacterWidget。
* 所有行为都可以在设置窗口里单独关掉。
"""

import math
import random
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, QPoint, QElapsedTimer, Signal
from PySide6.QtGui import QGuiApplication


class State:
    IDLE = "idle"  # 站着发呆，等下一次行为
    WALK = "walk"  # 在桌面上走动
    ACTION = "action"  # 播放一次性小动作 / 表情反应
    DRAG = "drag"  # 被鼠标拎着
    THROWN = "thrown"  # 抛出后下落、弹跳、滑行
    SLEEP = "sleep"  # 睡觉
    TALK = "talk"  # 正在说话（TTS 播放中）


SLEEP_LINES = [
    "すぅ…すぅ…",
    "むにゃ…Pくん…",
    "zzz…",
    "すやぁ…",
]
WAKE_LINES = [
    "んぅ…あと5分…",
    "ふぁ…おはよ…Pくん…",
    "んっ…おきたよぉ…",
]
DRAG_LINES = [
    "うわっ、なにするのぉ！",
    "ちょっ、Pくん！？",
    "たかいたかい…？",
]
LAND_LINES = [
    "いたたた…",
    "もうっ、乱暴だよぉ！",
    "ふぅ…びっくりした…",
]


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


class BehaviorEngine(QObject):
    moved = Signal(QPoint)  # 请求把窗口移到该坐标
    state_changed = Signal(str)  # 状态变化
    bubble = Signal(str, int)  # 想说的一句话 + 显示毫秒
    sleep_changed = Signal(bool)  # 睡着 / 醒来
    form_changed = Signal(str)  # 形象切换（cho=超天酱 / ame=糖糖），音色跟着换

    TICK_MS = 16
    SLEEP_WATCH_S = 5.0  # 睡着时每隔几秒确认一次"是不是该醒了"

    def __init__(self, cfg, lib, character, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.lib = lib
        self.character = character
        self._b = cfg.get("behavior", {})
        self._base_form = self._b.get("form", "cho")
        if self._base_form not in ("cho", "ame"):
            self._base_form = "cho"
        self._form = self._base_form

        self.pos = [0.0, 0.0]
        self.vel = [0.0, 0.0]
        self._state = State.IDLE
        self._sleeping = False

        # 空闲调度
        self._idle_left = 3.0
        self._action_left = 0.0

        # 走动
        self._walk_target = 0.0
        self._walk_dir = 1
        self._phase = 0.0

        # 拖拽
        self._grab_off = QPoint(0, 0)
        self._drag_target = [0.0, 0.0]

        self._bounces = 0

        # 手动覆盖睡眠（托盘菜单点"睡吧/醒来"）
        self._override = None
        self._override_base = None
        self._sleep_watch = 0.0

        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self):
        self._clock.start()
        self._timer.start(self.TICK_MS)
        self._settle_on_ground()
        self._apply_idle_anim()
        if self._want_sleep():
            self._enter_sleep(announce=False)
        else:
            self._schedule_next()

    def stop(self):
        self._timer.stop()

    def _settle_on_ground(self):
        self.pos[1] = float(self._ground_y())
        self.vel = [0.0, 0.0]

    # ------------------------------------------------------------------
    # 屏幕与边界
    # ------------------------------------------------------------------
    def _area(self):
        """窗口中心所在屏幕的可用区域（自动跟随多显示器）。"""
        cx = int(self.pos[0] + self.character.width() / 2)
        cy = int(self.pos[1] + self.character.height() / 2)
        scr = QGuiApplication.screenAt(QPoint(cx, cy)) or QGuiApplication.primaryScreen()
        return scr.availableGeometry()

    def _union_area(self):
        """所有屏幕的并集，用于限制拖拽范围（可以拖到别的显示器，但不能拖到屏幕外）。"""
        rects = [s.availableGeometry() for s in QGuiApplication.screens()]
        if not rects:
            return self._area()
        u = rects[0]
        for r in rects[1:]:
            u = u.united(r)
        return u

    def _ground_y(self):
        a = self._area()
        return float(a.bottom() - self.character.height() + 1)

    def _x_limits(self):
        a = self._area()
        return float(a.left()), float(a.right() - self.character.width() + 1)

    def area_changed(self):
        """显示器布局变化后把角色拉回可见范围；没有惯性时也用它直接落地。"""
        lo, hi = self._x_limits()
        self.pos[0] = _clamp(self.pos[0], lo, hi)
        self.pos[1] = self._ground_y()
        self.vel = [0.0, 0.0]
        self._emit_move()

    # ------------------------------------------------------------------
    # 对外查询
    # ------------------------------------------------------------------
    def is_sleeping(self):
        return self._sleeping

    def state(self):
        return self._state

    def current_form(self):
        """当前形象：cho=超天酱，ame=糖糖（睡觉时可能是睡姿形象）。"""
        return self._form

    def base_form(self):
        return self._base_form

    # ------------------------------------------------------------------
    # 形象切换（决定待机动画与音色）
    # ------------------------------------------------------------------
    def _effective_form(self):
        if self._sleeping:
            f = self._b.get("sleep_form", "cho")
            return f if f in ("cho", "ame") else "cho"
        return self._base_form

    def _refresh_form(self):
        f = self._effective_form()
        if f != self._form:
            self._form = f
            self.form_changed.emit(f)

    def set_form(self, form):
        """手动切换成超天酱 / 糖糖（同时换音色）。"""
        if form not in ("cho", "ame") or form == self._base_form:
            return False
        self._base_form = form
        self._b["form"] = form
        was = self._form
        self._form = self._effective_form()
        if not self._sleeping:
            self.character.set_default_loop(self.lib.idle_anim(self._form))
            self.character.play_idle()
        if self._form != was:
            self.form_changed.emit(self._form)
        return True

    def toggle_form(self):
        return self.set_form("ame" if self._base_form == "cho" else "cho")

    def set_position(self, x, y):
        self.pos = [float(x), float(y)]
        self.vel = [0.0, 0.0]

    def current_pos(self):
        return QPoint(int(self.pos[0]), int(self.pos[1]))

    # ------------------------------------------------------------------
    # 定时器主循环
    # ------------------------------------------------------------------
    def _tick(self):
        dt = self._clock.restart() / 1000.0
        dt = min(max(dt, 0.0), 0.05)  # 卡顿后不要瞬移

        # 睡着时 _update_rest 会直接 return，所以必须在这里定期回头看作息：
        # 否则她一睡下去就再也不会自己醒（只有被点/被搭话/被拖才会醒）。
        if self._sleeping:
            self._sleep_watch -= dt
            if self._sleep_watch <= 0:
                self._sleep_watch = self.SLEEP_WATCH_S
                if not self._want_sleep():
                    self.wake(manual=False)

        st = self._state
        if st == State.DRAG:
            self._update_drag(dt)
        elif st == State.THROWN:
            self._update_physics(dt)
        elif st == State.WALK:
            self._update_walk(dt)
        else:
            self._update_rest(dt)

    # ---------------- 静止类状态 ----------------
    def _update_rest(self, dt):
        if self._state == State.ACTION:
            self._action_left -= dt
            if self._action_left <= 0:
                self._to_idle()
                return

        if self._sleeping or self._state == State.TALK:
            return

        # 平时贴地站立；如果被拖到别处落地过，这里再校正一次
        gy = self._ground_y()
        if abs(self.pos[1] - gy) > 0.5:
            self.pos[1] = gy
            self._emit_move()

        self._idle_left -= dt
        if self._idle_left <= 0:
            self._decide_next()

    def _decide_next(self):
        # 总开关关掉时，只站着发呆
        if not self._b.get("enabled", True):
            self._schedule_next()
            return
        # 到点了就去睡
        if self._want_sleep():
            self._enter_sleep()
            return
        b = self._b
        roll = random.random()
        if b.get("roaming", True) and roll < 0.6:
            if self._start_walk():
                return
        if b.get("idle_action", True):
            if self._do_idle_action():
                return
        self._schedule_next()

    def _schedule_next(self):
        if self._sleeping:
            self._idle_left = 20.0
            return
        lo = float(self._b.get("idle_action_min", 20))
        hi = float(self._b.get("idle_action_max", 65))
        if hi < lo:
            lo, hi = hi, lo
        self._idle_left = random.uniform(lo, hi)

    # ---------------- 走动 ----------------
    def _start_walk(self):
        lo, hi = self._x_limits()
        dist = random.randint(110, 340)
        first = random.choice((-1, 1))
        target = None
        # 贴着屏幕边缘时，如果选的朝向走不动就换另一边
        for d in (first, -first):
            cand = _clamp(self.pos[0] + d * dist, lo, hi)
            if abs(cand - self.pos[0]) >= 60:
                target = cand
                break
        if target is None:
            return False
        self._walk_target = target
        self._walk_dir = 1 if target > self.pos[0] else -1
        self._phase = 0.0
        self.character.set_default_loop(self.lib.pick_walk(self._form))
        self.character.set_flip(self._walk_dir < 0)
        self._set_state(State.WALK)
        return True

    def _update_walk(self, dt):
        if self._sleeping:
            self._stop_walk()
            return
        speed = float(self._b.get("walk_speed", 55))
        self.pos[0] += self._walk_dir * speed * dt
        done = (self._walk_dir > 0 and self.pos[0] >= self._walk_target) or (
            self._walk_dir < 0 and self.pos[0] <= self._walk_target
        )
        if done:
            self.pos[0] = self._walk_target
            self._stop_walk()
            return

        # 上下起伏 + 轻微左右摇摆，做出"在走路"的感觉
        self._phase += dt * float(self._b.get("step_rate", 2.2))
        bob = -abs(math.sin(math.pi * self._phase)) * float(self._b.get("bob_px", 4))
        leg = 1 if int(self._phase) % 2 == 0 else -1
        tilt = math.sin(math.pi * self._phase) * float(self._b.get("tilt_deg", 1.2)) * leg
        self.character.set_bob(bob)
        self.character.set_tilt(tilt)
        self._emit_move()

    def _stop_walk(self):
        self.character.reset_pose()
        self._apply_idle_anim()
        self._to_idle()

    # ---------------- 小动作 ----------------
    def _do_idle_action(self):
        pick = self.lib.pick_idle_action(self._form)
        if not pick:
            return False
        anim, fps = pick
        self.play_reaction(anim, fps)
        return True

    def play_reaction(self, anim, fps=None, seconds=None):
        """播放一次性动作，期间不安排走动。"""
        if not anim:
            return
        if self._state == State.WALK:
            # 从走动中被打断：先停下并收掉晃动/翻面
            self.character.reset_pose()
        if fps is None:
            self.character.play_emotion(anim)
            fps = self.character.fps
        else:
            self.character.play_emotion(anim, fps)
        self._action_left = seconds if seconds is not None else self.lib.anim_duration_ms(anim, fps) / 1000.0
        self._set_state(State.ACTION)

    def stop_walking(self):
        if self._state == State.WALK:
            self._stop_walk()

    def refresh_sleep(self):
        """行为开关变化后重新判定该不该睡。"""
        if self._want_sleep():
            if not self._sleeping:
                self._enter_sleep()
        elif self._sleeping:
            self.wake(manual=False)

    def _to_idle(self):
        self._apply_idle_anim()
        # 真正切回待机动画：TALK 是循环模式，set_default_loop 只在当前也是循环时才立即切换，
        # 不主动切的话她说完话会一直循环"说话"动画（一直在动嘴）。
        if not self._sleeping:
            self.character.play_idle()
        self._set_state(State.IDLE)
        self._schedule_next()

    def _apply_idle_anim(self):
        """按当前形象把待机动画设为默认循环。"""
        if self._sleeping:
            return
        self.character.set_default_loop(self.lib.idle_anim(self._form))

    # ---------------- 说话 ----------------
    def notify_talking(self, talking):
        if talking:
            if self._sleeping:
                # 被叫起来聊天了
                self.wake(manual=True)
            if self._state in (State.DRAG, State.THROWN):
                return
            # 走动中被打断时先收掉走动姿势，否则她会歪着/悬着说话
            self.character.reset_pose()
            self.character.play_talk(self.lib.pick_talk(self._form))
            self._set_state(State.TALK)
        else:
            if self._state == State.TALK:
                if self._sleeping:
                    self._enter_sleep(announce=False)
                else:
                    self._to_idle()

    # ---------------- 物理：抛出 / 下落 / 滑行 ----------------
    def _update_physics(self, dt):
        g = float(self._b.get("gravity", 2200))
        self.vel[1] += g * dt
        self.pos[0] += self.vel[0] * dt
        self.pos[1] += self.vel[1] * dt

        lo, hi = self._x_limits()
        if self.pos[0] < lo:
            self.pos[0] = lo
            self.vel[0] = -self.vel[0] * 0.5
        elif self.pos[0] > hi:
            self.pos[0] = hi
            self.vel[0] = -self.vel[0] * 0.5

        top = float(self._area().top())
        if self.pos[1] < top:
            self.pos[1] = top
            self.vel[1] = abs(self.vel[1]) * 0.35  # 撞到屏幕顶端就往下弹

        gy = self._ground_y()
        grounded = False
        if self.pos[1] >= gy:
            self.pos[1] = gy
            if self.vel[1] > 340 and self._bounces < 3:
                self.vel[1] = -self.vel[1] * float(self._b.get("throw_bounce", 0.42))
                self._bounces += 1
            else:
                self.vel[1] = 0.0
                grounded = True

        if grounded:
            self.vel[0] *= float(self._b.get("ground_friction", 0.86)) ** (dt * 60)
            if abs(self.vel[0]) < 16:
                self.vel[0] = 0.0
                self._bounces = 0
                if random.random() < 0.5:
                    self.bubble.emit(random.choice(LAND_LINES), 2200)
                self.character.reset_pose()
                self._to_idle()
                return

        self._emit_move()

    # ---------------- 拖拽 ----------------
    def on_press(self, global_pos):
        self._grab_off = QPoint(int(self.pos[0]) - global_pos.x(), int(self.pos[1]) - global_pos.y())
        self._drag_target = [self.pos[0], self.pos[1]]
        self.vel = [0.0, 0.0]
        self._bounces = 0
        if self._sleeping:
            self.wake(manual=True)
        self.character.play_loop(self.lib.pick_drag(self._form), fps=10)
        self._set_state(State.DRAG)
        if random.random() < 0.5:
            self.bubble.emit(random.choice(DRAG_LINES), 1800)

    def on_drag(self, global_pos):
        if self._state != State.DRAG:
            return
        x = global_pos.x() + self._grab_off.x()
        y = global_pos.y() + self._grab_off.y()
        u = self._union_area()
        w, h = self.character.width(), self.character.height()
        self._drag_target = [_clamp(x, u.left(), u.right() - w + 1), _clamp(y, u.top(), u.bottom() - h + 1)]

    def _update_drag(self, dt):
        if dt <= 0:
            return
        # 弹簧跟随：让她稍微"落后"于鼠标，有一点点重量感
        k = float(self._b.get("drag_follow", 26.0))
        alpha = 1.0 - math.exp(-k * dt)
        dx = (self._drag_target[0] - self.pos[0]) * alpha
        dy = (self._drag_target[1] - self.pos[1]) * alpha
        self.pos[0] += dx
        self.pos[1] += dy
        # 用指数滑动平均估计释放瞬间的速度
        self.vel[0] = self.vel[0] * 0.72 + (dx / dt) * 0.28
        self.vel[1] = self.vel[1] * 0.72 + (dy / dt) * 0.28
        self._emit_move()

    def on_release(self):
        if self._state != State.DRAG:
            return
        if not self._b.get("enabled", True) or not self._b.get("drag_inertia", True):
            self.area_changed()
            self.character.reset_pose()
            self._to_idle()
            return
        mx = float(self._b.get("max_throw_speed", 2400))
        vx = _clamp(self.vel[0], -mx, mx)
        vy = _clamp(self.vel[1], -mx, mx)
        if abs(vx) < 45 and abs(vy) < 45:
            vx = vy = 0.0
        # 保证她至少会掉到地面
        self.pos[1] = min(self.pos[1], self._ground_y())
        if abs(vx) < 45 and abs(vy) < 45:
            self._bounces = 0
            self.character.reset_pose()
            self._to_idle()
            return
        self.vel = [vx, vy]
        self._bounces = 0
        self._set_state(State.THROWN)

    # ---------------- 点击 ----------------
    def on_click(self):
        if self._sleeping:
            self.wake(manual=True)
            return
        if self._state == State.TALK:
            return
        if self.cfg.get("pet", {}).get("click_animations", True):
            self.play_reaction(self.lib.pick_click(self._form), fps=8)

    # ---------------- 睡觉 ----------------
    def _schedule_says_sleep(self):
        if not self._b.get("enabled", True):
            return False
        if not self._b.get("sleep_enabled", True):
            return False
        try:
            now = datetime.now().time()
            sh, sm = [int(x) for x in str(self._b.get("sleep_start", "23:30")).split(":")]
            eh, em = [int(x) for x in str(self._b.get("sleep_end", "07:00")).split(":")]
        except Exception:
            return False
        start = sh * 60 + sm
        end = eh * 60 + em
        cur = now.hour * 60 + now.minute
        if start == end:
            return False
        if start < end:
            return start <= cur < end
        return cur >= start or cur < end  # 跨过午夜

    def _want_sleep(self):
        sched = self._schedule_says_sleep()
        if self._override is not None and sched == self._override_base:
            return self._override
        self._override = None
        return sched

    def _enter_sleep(self, announce=True):
        was = self._sleeping
        self._sleeping = True
        self._sleep_watch = self.SLEEP_WATCH_S
        self._refresh_form()  # 睡觉可能换成糖糖（素颜）
        self.vel = [0.0, 0.0]
        self.pos[1] = float(self._ground_y())
        anim = self.lib.sleep_anim(self._form)
        fps = float(self._b.get("sleep_loop_fps", 4))
        self.character.reset_pose()
        self.character.set_default_loop(anim, fps)
        self.character.play_loop(anim, fps)
        self._set_state(State.SLEEP)
        self._emit_move()
        if announce and not was:
            self.bubble.emit(random.choice(SLEEP_LINES), 2600)
        if not was:
            self.sleep_changed.emit(True)

    def wake(self, manual=False):
        was = self._sleeping
        self._sleeping = False
        self._refresh_form()
        if manual:
            # 手动叫醒后，本轮作息内不要再自动睡回去
            self._override = False
            self._override_base = self._schedule_says_sleep()
        self.character.set_default_loop(self.lib.idle_anim(self._form))
        anim = self.lib.pick_wake(self._form)
        self.play_reaction(anim, fps=8)
        self._action_left = max(self._action_left, 1.6)
        if random.random() < 0.8:
            self.bubble.emit(random.choice(WAKE_LINES), 2400)
        if was:
            self.sleep_changed.emit(False)

    def toggle_sleep(self):
        """托盘菜单：让她睡 / 叫醒她。"""
        if self._sleeping:
            self.wake(manual=True)
        else:
            self._override = True
            self._override_base = self._schedule_says_sleep()
            self._enter_sleep()

    # ---------------- 工具 ----------------
    def _set_state(self, st):
        if st != self._state:
            self._state = st
            self.state_changed.emit(st)

    def _emit_move(self):
        self.moved.emit(QPoint(int(self.pos[0]), int(self.pos[1])))
