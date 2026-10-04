# -*- coding: utf-8 -*-
"""行为引擎的离线测试：用固定屏幕区域 + 假时钟，逐帧推进状态机并断言。

运行：.venv\\Scripts\\python.exe tools\\test_behavior.py
"""
import os, sys, io
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRect, QPoint

from pet.character_anim import AnimationLibrary
from pet.anim_player import CharacterWidget
from pet.behavior import BehaviorEngine, State
import pet.config as config

app = QApplication.instance() or QApplication(sys.argv)

SCREEN = QRect(0, 0, 1920, 1040)      # 可用区域（已扣掉任务栏）


class FakeClock:
    def __init__(self, dt_ms=16):
        self.dt_ms = dt_ms

    def start(self):
        pass

    def restart(self):
        return self.dt_ms


def make_engine(**behavior_overrides):
    cfg = {"pet": {"click_animations": True}, "behavior": dict(config.DEFAULT_CONFIG["behavior"])}
    # 作息是按真实时间判断的，默认关掉，否则这套测试在晚上跑结果会不一样
    cfg["behavior"]["sleep_enabled"] = False
    cfg["behavior"].update(behavior_overrides)
    lib = AnimationLibrary()
    ch = CharacterWidget(lib, fps=12, scale=1.0)
    eng = BehaviorEngine(cfg, lib, ch)
    eng._area = lambda: SCREEN                     # 固定屏幕，测试不依赖真实显示器
    eng._union_area = lambda: SCREEN
    eng._clock = FakeClock()
    moves = []
    eng.moved.connect(lambda p: moves.append((p.x(), p.y())))
    return eng, ch, lib, moves


def frames(eng, n, dt_ms=16):
    eng._clock.dt_ms = dt_ms
    for _ in range(n):
        eng._tick()


def check(label, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILURES.append(label)


FAILURES = []

# ---------------------------------------------------------------- 1. 落地与待机
eng, ch, lib, moves = make_engine()
eng.start()
ground = SCREEN.bottom() - ch.height() + 1
check("启动后站在地面", abs(eng.pos[1] - ground) < 1, f"y={eng.pos[1]:.1f} ground={ground}")
check("启动状态为待机", eng.state() in (State.IDLE, State.SLEEP), eng.state())

# ---------------------------------------------------------------- 2. 走动
eng, ch, lib, moves = make_engine(idle_action=False)
eng.start()
start_x = eng.pos[0]
ok = eng._start_walk()
check("可以进入走动状态", ok and eng.state() == State.WALK, eng.state())
bob_seen = False
for _ in range(400):
    frames(eng, 1)
    if ch._bob != 0:
        bob_seen = True
    if eng.state() != State.WALK:
        break
check("走动过程中有上下起伏", bob_seen)
check("走到目标后停下", eng.state() == State.IDLE, eng.state())
check("走动确实改变了横坐标", abs(eng.pos[0] - start_x) > 50, f"{start_x:.0f} -> {eng.pos[0]:.0f}")
check("停下后晃动归零", ch._bob == 0 and abs(ch._tilt) < 0.01)
check("走动没有跑出屏幕", SCREEN.left() <= eng.pos[0] <= SCREEN.right() - ch.width() + 1)

# ---------------------------------------------------------------- 3. 拖拽 + 惯性抛出
eng, ch, lib, moves = make_engine()
eng.start()
press = QPoint(600, ground)
eng.on_press(press)
check("按下后进入拖拽状态", eng.state() == State.DRAG, eng.state())
drag_x = 600
for _ in range(25):                     # 每帧向右 30px，模拟快速甩动
    drag_x += 30
    eng.on_drag(QPoint(drag_x, ground - 120))
    frames(eng, 1)
check("拖拽时跟随鼠标（略有滞后）", eng.pos[0] > press.x(), f"x={eng.pos[0]:.0f}")
vx_at_release = eng.vel[0]
eng.on_release()
check("松手后进入抛出状态", eng.state() == State.THROWN, eng.state())
check("松手时带有向右的速度", vx_at_release > 300, f"vx={vx_at_release:.0f}")
x_at_release = eng.pos[0]
airborne = not (abs(eng.pos[1] - ground) < 1)
for _ in range(900):
    frames(eng, 1)
    if eng.state() == State.IDLE:
        break
check("抛出后最终回到待机", eng.state() == State.IDLE, eng.state())
check("抛出后滑行了一段距离", eng.pos[0] - x_at_release > 100, f"+{eng.pos[0] - x_at_release:.0f}px")
check("最终落在地面", abs(eng.pos[1] - ground) < 1, f"y={eng.pos[1]:.1f}")
check("没有飞出屏幕", SCREEN.left() <= eng.pos[0] <= SCREEN.right() - ch.width() + 1)

# 无惯性模式下松手应直接落地
eng, ch, lib, moves = make_engine(drag_inertia=False)
eng.start()
eng.on_press(QPoint(600, ground))
eng.on_drag(QPoint(900, ground - 200))
frames(eng, 5)
eng.on_release()
check("关掉惯性后松手立刻回待机", eng.state() == State.IDLE, eng.state())
check("关掉惯性后仍被拉回地面", abs(eng.pos[1] - ground) < 1, f"y={eng.pos[1]:.1f}")

# ---------------------------------------------------------------- 4. 空闲小动作
eng, ch, lib, moves = make_engine()
eng.start()
did = eng._do_idle_action()
check("可以触发空闲小动作", did and eng.state() == State.ACTION, eng.state())
anim_during = ch.current_anim()
for _ in range(600):
    frames(eng, 1)
    if eng.state() != State.ACTION:
        break
check("小动作播完回到待机", eng.state() == State.IDLE, eng.state())
check("小动作期间播放了动画", bool(anim_during), anim_during or "")

# ---------------------------------------------------------------- 5. 夜间睡觉
eng, ch, lib, moves = make_engine()
eng.start()
eng.toggle_sleep()
check("手动睡觉进入睡眠状态", eng.is_sleeping() and eng.state() == State.SLEEP, eng.state())
expected_sleep = lib.sleep_anim(eng._b.get("sleep_form", "cho"))
check("睡觉用的是配置里指定的睡姿", ch.current_anim() == expected_sleep,
      f"{ch.current_anim()} (期望 {expected_sleep})")
before_x = eng.pos[0]
frames(eng, 600)
check("睡觉期间不会走动", abs(eng.pos[0] - before_x) < 1 and eng.state() == State.SLEEP,
      f"{before_x:.0f} -> {eng.pos[0]:.0f}, {eng.state()}")
check("睡姿是逐帧循环（loop 模式）", ch._mode == ch.MODE_LOOP, ch._mode)
eng.wake(manual=True)
check("叫醒后退出睡眠", (not eng.is_sleeping()) and eng.state() == State.ACTION, eng.state())
for _ in range(400):
    frames(eng, 1)
    if eng.state() == State.IDLE:
        break
check("醒来后回到待机", eng.state() == State.IDLE, eng.state())

# 换回超天酱睡姿
eng2, ch2, lib2, _ = make_engine(sleep_form="cho")
eng2.start()
eng2.toggle_sleep()
check("sleep_form=cho 时用超天酱睡姿", ch2.current_anim() == lib2.sleep_anim("cho"), str(ch2.current_anim()))
for _ in range(400):
    frames(eng, 1)
    if eng.state() == State.IDLE:
        break
check("醒来后回到待机", eng.state() == State.IDLE, eng.state())

# 作息时间段判断
eng, ch, lib, moves = make_engine(sleep_enabled=True, sleep_start="00:00", sleep_end="23:59")
check("作息覆盖全天时应判定为睡觉时间", eng._schedule_says_sleep() is True)
eng, ch, lib, moves = make_engine(sleep_enabled=True, sleep_start="03:00", sleep_end="03:01")
check("作息之外的时段不睡觉", eng._schedule_says_sleep() is False)
eng, ch, lib, moves = make_engine(sleep_enabled=False)
check("关掉夜间睡觉后不睡", eng._schedule_says_sleep() is False)

# ---------------------------------------------------------------- 6. 说话期间不乱跑
eng, ch, lib, moves = make_engine()
eng.start()
eng.notify_talking(True)
check("说话时进入 TALK 状态", eng.state() == State.TALK, eng.state())
before = eng.pos[0]
frames(eng, 200)
check("说话时不会走动", abs(eng.pos[0] - before) < 1, f"{before:.0f} -> {eng.pos[0]:.0f}")
eng.notify_talking(False)
check("说完话回到待机", eng.state() == State.IDLE, eng.state())
check("说完话动画也切回待机（不是继续循环说话动画）",
      ch.current_anim() == lib.idle_anim("cho") and ch._mode == ch.MODE_LOOP,
      f"{ch.current_anim()} mode={ch._mode}")

# 睡着时说话会把她叫醒
eng, ch, lib, moves = make_engine()
eng.start()
eng.toggle_sleep()
eng.notify_talking(True)
check("睡着时说话会叫醒她", not eng.is_sleeping(), eng.state())

# ---------------------------------------------------------------- 7. 形象切换（决定音色）
eng, ch, lib, moves = make_engine()
forms = []
eng.form_changed.connect(forms.append)
eng.start()
check("默认形象是超天酱", eng.current_form() == "cho", eng.current_form())
check("超天酱待机用的是超天酱动画", ch.current_anim() == lib.idle_anim("cho"), str(ch.current_anim()))

eng.set_form("ame")
check("可以切换到糖糖", eng.current_form() == "ame", eng.current_form())
check("切换形象会发出 form_changed", forms == ["ame"], str(forms))
check("糖糖待机用的是糖糖动画", ch.current_anim() == lib.idle_anim("ame"), str(ch.current_anim()))

# 糖糖形态下走动/小动作/说话都要用糖糖的池子
eng._start_walk()
check("糖糖走路用糖糖的走路动画", ch.current_anim() in lib._t("ame", "walk"),
      str(ch.current_anim()))
eng._stop_walk()
pick = lib.pick_idle_action("ame")
check("糖糖的小动作来自糖糖池", pick is not None and pick[0].startswith("stream_ame_"), str(pick))
eng.notify_talking(True)
check("糖糖说话用糖糖的说话动画", ch.current_anim() in lib._t("ame", "talk"),
      str(ch.current_anim()))
eng.notify_talking(False)

# 睡觉形象 & 醒来回到用户选的糖糖
eng2, ch2, lib2, _ = make_engine(form="ame", sleep_form="cho")
forms2 = []
eng2.form_changed.connect(forms2.append)
eng2.start()
check("启动时就是糖糖形象", eng2.current_form() == "ame", eng2.current_form())
eng2.toggle_sleep()
check("睡觉时切到 sleep_form 指定的形象", eng2.current_form() == "cho", eng2.current_form())
check("睡觉形象变化也会通知（音色要跟着换）", forms2 == ["cho"], str(forms2))
eng2.wake(manual=True)
check("醒来回到用户选的糖糖形象", eng2.current_form() == "ame", eng2.current_form())

check("toggle_form 能来回切", (eng2.toggle_form() is True) and eng2.base_form() == "cho")
check("切到相同形象时什么都不做", eng2.set_form("cho") is False)

# ---------------------------------------------------------------- 8. 到点自己醒来
# 回归：以前 _update_rest 在睡着时直接 return，作息判定再也不会被求值，
# 结果她一睡下去就只能被点/被搭话才会醒。
import pet.behavior as behavior_mod


class _Time:
    def __init__(self, h, m):
        self.hour, self.minute = h, m


class _FakeNow:
    def __init__(self, t):
        self._t = t

    def time(self):
        return self._t


class _FakeDateTime:
    cur = None

    @classmethod
    def now(cls):
        return _FakeNow(cls.cur)


_real_datetime = behavior_mod.datetime
behavior_mod.datetime = _FakeDateTime
try:
    _FakeDateTime.cur = _Time(23, 45)
    eng, ch, lib, moves = make_engine(sleep_enabled=True,
                                      sleep_start="23:30", sleep_end="07:00")
    eng.start()
    check("到了作息时间会自己睡着",
          eng.is_sleeping() and eng.state() == State.SLEEP, eng.state())

    _FakeDateTime.cur = _Time(8, 0)
    check("时间走到作息之外后判定不再是睡觉时间", eng._want_sleep() is False)
    frames(eng, 400)                    # 400 × 16ms = 6.4s，超过 5 秒的检查间隔
    check("过了作息时间会自己醒过来", not eng.is_sleeping(), eng.state())
    check("醒来后不再停留在睡眠状态", eng.state() != State.SLEEP, eng.state())

    # 手动「让她睡一会儿」：作息没翻转之前保持睡，走完一轮作息后要能自己醒
    _FakeDateTime.cur = _Time(14, 0)
    eng2, ch2, lib2, _ = make_engine(sleep_enabled=True,
                                     sleep_start="23:30", sleep_end="07:00")
    eng2.start()
    eng2.toggle_sleep()
    check("手动让她睡会睡着", eng2.is_sleeping(), eng2.state())
    frames(eng2, 400)
    check("手动睡眠不会马上被自动醒来打断", eng2.is_sleeping(), eng2.state())

    _FakeDateTime.cur = _Time(23, 45)   # 进入作息：仍然应该睡着
    frames(eng2, 400)
    check("手动睡眠进入作息后继续睡", eng2.is_sleeping(), eng2.state())

    _FakeDateTime.cur = _Time(8, 0)     # 走出作息：这时才该醒
    frames(eng2, 400)
    check("手动睡眠走到作息结束也会醒", not eng2.is_sleeping(), eng2.state())
finally:
    behavior_mod.datetime = _real_datetime

# ---------------------------------------------------------------- 9. 说话打断走动
eng, ch, lib, moves = make_engine(idle_action=False)
eng.start()
eng._start_walk()
frames(eng, 40)
check("走动中确实有起伏或倾斜", ch._bob != 0 or abs(ch._tilt) > 0.01,
      f"bob={ch._bob} tilt={ch._tilt:.2f}")
eng.notify_talking(True)
check("说话打断走动后姿势复位", ch._bob == 0 and abs(ch._tilt) < 0.01,
      f"bob={ch._bob} tilt={ch._tilt:.2f}")
eng.notify_talking(False)
check("说完话回到待机", eng.state() == State.IDLE, eng.state())
check("被打断走动后也说回了待机动画", ch.current_anim() == lib.idle_anim("cho"),
      str(ch.current_anim()))

# ---------------------------------------------------------------- 10. 帧缓存有上限
ch3 = CharacterWidget(lib, fps=12, scale=1.0)
ch3.CACHE_MAX = 3
names = [a for a in lib.manifest if lib.has(a)][:10]
check("素材里有足够的动画可测", len(names) >= 4, len(names))
for a in names:
    ch3._load_pixmaps(a)
check("帧缓存不会无限增长", len(ch3._cache) <= 3, len(ch3._cache))
check("刚用过的动画留在缓存里", names[-1] in ch3._cache)
check("缓存里最旧的已被淘汰", names[0] not in ch3._cache, str(list(ch3._cache)))

print()
if FAILURES:
    print(f"{len(FAILURES)} 项失败: {FAILURES}")
    sys.exit(1)
print("全部通过 ✔")
