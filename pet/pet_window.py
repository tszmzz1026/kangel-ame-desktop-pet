# -*- coding: utf-8 -*-
"""桌宠主窗口：整合角色、行为引擎、对话面板、LLM、TTS、视觉、托盘菜单、自启动。"""

import os, random, time
from typing import Callable

from PySide6.QtWidgets import (
    QWidget,
    QApplication,
    QMenu,
    QSystemTrayIcon,
    QMessageBox,
)
from PySide6.QtGui import QIcon, QAction, QGuiApplication, QCursor
from PySide6.QtCore import (
    Qt,
    QTimer,
    QObject,
    QThread,
    Signal,
    QPoint,
)

from . import config, autostart, logsetup
from .character_anim import AnimationLibrary
from .anim_player import CharacterWidget
from .behavior import BehaviorEngine
from .bubble import SpeechBubble
from .chat_panel import ChatPanel
from .llm import LLMClient
from .build_info import APP_NAME, TTS_AVAILABLE
from . import vision
from . import persona

log = logsetup.install()

# 头顶气泡距离窗口顶部的偏移（角色头部大约在这里）
BUBBLE_ANCHOR_Y = 58


class Worker(QObject):
    done = Signal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:
            print("worker err", e, flush=True)
            self.done.emit({"emotion": "sad", "text": f"（出错了：{e}）", "zh": "", "options": []})


class PetWindow(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.busy = False
        self._exit_callback: Callable[[], None] | None = None
        self._threads = []
        self._workers = []
        self._dragging = False
        self._press_global = QPoint(0, 0)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self.lib = AnimationLibrary()
        self.llm = LLMClient(cfg)
        if TTS_AVAILABLE:
            from .tts import TTSClient

            self.tts = TTSClient(cfg, self)
        else:
            from .silent_tts import SilentTTSClient

            self.tts = SilentTTSClient(cfg, self)

        self.character = CharacterWidget(self.lib, fps=cfg["pet"]["fps"], scale=cfg["pet"]["scale"])
        self.character.setParent(self)
        self.character.move(0, 0)
        self.setFixedSize(self.character.size())

        # 头顶气泡（说日语短句用，独立顶层小窗，不抢焦点）
        self.bubble = SpeechBubble()

        # 行为引擎：走动 / 拖拽惯性 / 小动作 / 夜间睡觉 / 形象与音色
        self.engine = BehaviorEngine(cfg, self.lib, self.character, self)
        self.engine.moved.connect(self._on_engine_moved)
        self.engine.bubble.connect(self._on_bubble)
        self.engine.sleep_changed.connect(self._on_sleep_changed)
        self.engine.form_changed.connect(self._on_form_changed)

        # 跟随节流：走动时不用每一帧都重排对话面板
        self._follow_timer = QTimer(self)
        self._follow_timer.setSingleShot(True)
        self._follow_timer.timeout.connect(self._follow)

        # TTS 信号（跨线程）安全地驱动说话/待机动画与行为
        self.tts.started.connect(self._on_tts_started)
        self.tts.finished.connect(self._on_tts_finished)

        self.chat_panel = ChatPanel()
        self.chat_panel.submitted.connect(self.handle_user_text)
        self.chat_panel.option_clicked.connect(self.handle_user_text)
        self.chat_panel.resized.connect(self._place_panel)

        self._init_tray()
        self._init_position()

        # 主动观察（截屏）
        self.vision_timer = QTimer(self)
        self.vision_timer.setSingleShot(True)
        self.vision_timer.timeout.connect(self.proactive_screen)
        if cfg["vision"]["enabled"]:
            QTimer.singleShot(90_000, self._arm_vision)

        # 空闲主动搭话
        self.chitchat_timer = QTimer(self)
        self.chitchat_timer.setSingleShot(True)
        self.chitchat_timer.timeout.connect(self.proactive_chitchat)
        QTimer.singleShot(180_000, self._arm_chitchat)

        # 显示器插拔后把角色拉回可见区域
        app = QApplication.instance()
        if app is not None:
            app.screenAdded.connect(lambda _s: self.engine.area_changed())
            app.screenRemoved.connect(lambda _s: self.engine.area_changed())

        self.engine.start()
        # 形象 -> 音色：超天酱用 kangel 模型，糖糖用 amechan 模型
        self._sync_voice(initial=True)
        # 启动就把 GPT-SoVITS API 拉起来并预热当前音色，否则第一句话要等 20~40 秒
        self.tts.warmup()

    # ---------------- 形象与音色 ----------------
    def _voice_for_form(self, form):
        t = self.cfg["tts"]
        if not t.get("voice_by_form", True):
            return t.get("default_voice") or "cho"
        return form if form in self.tts.voices() else (t.get("default_voice") or "cho")

    def _sync_voice(self, initial=False):
        key = self._voice_for_form(self.engine.current_form())
        changed = self.tts.set_voice(key)
        if changed:
            # 提前把权重加载进去，等真要说话时就不用等了
            self.tts.preload_voice(key)
        if changed or initial:
            self._refresh_voice_action()

    def _on_form_changed(self, form):
        name = self.tts.voice_names().get(form, form)
        self.bubble.show_text(f"{name}だよっ", 1800)
        self._place_bubble()
        self._sync_voice()
        self._refresh_form_action()

    def toggle_form(self):
        self.engine.toggle_form()
        b = self.cfg.setdefault("behavior", {})
        b["form"] = self.engine.base_form()
        config.save_config(self.cfg)
        self._refresh_form_action()

    # ---------------- 位置 ----------------
    def _init_position(self):
        """恢复上次位置：只沿用横坐标，纵坐标落到当前屏幕的地面。"""
        pos = self.cfg["pet"].get("pos")
        if pos and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
            scr = QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.primaryScreen()
            area = scr.availableGeometry()
            x = max(area.left(), min(x, area.right() - self.width() + 1))
            y = area.bottom() - self.height() + 1
        else:
            screen = QGuiApplication.primaryScreen().availableGeometry()
            x = screen.right() - self.width() - 30
            y = screen.bottom() - self.height() - 20
        self.move(x, y)
        self.engine.set_position(x, y)

    def _on_engine_moved(self, pos):
        self.move(pos)
        if not self._follow_timer.isActive():
            self._follow_timer.start(80)

    def _follow(self):
        """角色移动后，让气泡和对话面板跟上她。"""
        self._place_bubble()
        if self.chat_panel.isVisible():
            self._place_panel()

    def _screen_area(self):
        scr = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        return scr.availableGeometry()

    def _place_bubble(self):
        if not self.bubble.isVisible():
            return
        self.bubble.place_above(self.x(), self.y() + BUBBLE_ANCHOR_Y, self.width(), self._screen_area())

    def _place_panel(self):
        self.chat_panel.adjustSize()
        screen = self._screen_area()
        gp = self.frameGeometry()
        w = self.chat_panel.width()
        h = self.chat_panel.height()
        # 优先放在她左边；左边放不下就放右边；都放不下就贴着屏幕边
        x = gp.left() - w - 10
        if x < screen.left() + 5:
            x = gp.right() + 10
        x = max(screen.left() + 5, min(x, screen.right() - w - 5))
        y = gp.bottom() - h
        y = max(screen.top() + 5, min(y, screen.bottom() - h - 5))
        self.chat_panel.move(x, y)

    # ---------------- 气泡 ----------------
    def _on_bubble(self, text, ms):
        self.bubble.show_text(text, ms)
        self._place_bubble()

    def _on_sleep_changed(self, sleeping):
        self._refresh_sleep_action()
        if sleeping:
            self.bubble.show_text("おやすみ…Pくん…♡", 3000)
        else:
            self.bubble.show_text("おはよっ♡", 2200)
        self._place_bubble()

    # ---------------- 托盘 ----------------
    def _init_tray(self):
        icon = QIcon(os.path.join(config.ASSETS_DIR, "icon.ico"))
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        a_chat = menu.addAction("和超天酱聊天")
        a_screen = menu.addAction("看看我在干嘛（截屏）")
        a_settings = menu.addAction("设置（填 API Key）")
        a_log = menu.addAction("查看运行日志")

        b = self.cfg.get("behavior", {})
        self.a_form = menu.addAction("切换成糖糖（素颜）")
        self.a_form.triggered.connect(self.toggle_form)

        beh = menu.addMenu("桌宠行为")
        self.a_roaming = self._check_action(beh, "桌面走动", b.get("roaming", True), "roaming")
        self.a_idle_act = self._check_action(beh, "空闲小动作", b.get("idle_action", True), "idle_action")
        self.a_inertia = self._check_action(
            beh, "拖拽惯性（甩出去会飞）", b.get("drag_inertia", True), "drag_inertia"
        )
        self.a_sleep_sched = self._check_action(
            beh, "夜间自动睡觉", b.get("sleep_enabled", True), "sleep_enabled"
        )
        beh.addSeparator()
        self.a_sleep_now = beh.addAction("让她睡一会儿")
        self.a_sleep_now.triggered.connect(self.toggle_sleep)

        # 音色 / 语音
        voice = menu.addMenu("语音音色")
        voice.menuAction().setVisible(TTS_AVAILABLE)
        self.a_voice_by_form = voice.addAction("音色跟随形象（超天酱 / 糖糖）")
        self.a_voice_by_form.setCheckable(True)
        self.a_voice_by_form.setChecked(bool(self.cfg["tts"].get("voice_by_form", True)))
        self.a_voice_by_form.triggered.connect(self._toggle_voice_by_form)
        voice.addSeparator()
        self._voice_actions = {}
        for key, name in self.tts.voice_names().items():
            a = voice.addAction(f"用 {name} 的声音")
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, k=key: self._pick_voice(k))
            self._voice_actions[key] = a
        voice.addSeparator()
        self.a_preview = voice.addAction("试听当前音色")
        self.a_preview.triggered.connect(lambda: self.preview_voice())

        menu.addSeparator()
        a_clear = menu.addAction("清空记忆")
        self.a_autostart = QAction("开机自启动", menu)
        self.a_autostart.setCheckable(True)
        self.a_autostart.setChecked(autostart.is_enabled())
        menu.addAction(self.a_autostart)
        menu.addSeparator()
        a_quit = menu.addAction("退出")
        a_chat.triggered.connect(self.open_chat)
        a_screen.triggered.connect(self.manual_screen)
        a_settings.triggered.connect(self.open_settings)
        a_log.triggered.connect(self.open_log)
        a_clear.triggered.connect(self.clear_memory)
        self.a_autostart.triggered.connect(self.toggle_autostart)
        a_quit.triggered.connect(self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.open_chat() if reason == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()
        self._refresh_sleep_action()
        self._refresh_form_action()
        self._refresh_voice_action()

    def _check_action(self, menu, label, checked, key):
        """行为开关：勾选后立即生效并存盘。"""
        a = QAction(label, menu)
        a.setCheckable(True)
        a.setChecked(bool(checked))
        a.triggered.connect(lambda on, k=key: self._set_behavior(k, on))
        menu.addAction(a)
        return a

    def _set_behavior(self, key, on):
        self.cfg.setdefault("behavior", {})[key] = bool(on)
        config.save_config(self.cfg)
        if key == "roaming" and not on:
            self.engine.stop_walking()
        elif key == "sleep_enabled":
            self.engine.refresh_sleep()
        self._refresh_sleep_action()

    def _refresh_sleep_action(self):
        if not hasattr(self, "a_sleep_now"):
            return
        self.a_sleep_now.setText("叫醒她" if self.engine.is_sleeping() else "让她睡一会儿")

    def _refresh_form_action(self):
        if not hasattr(self, "a_form"):
            return
        ame = self.engine.base_form() == "ame"
        self.a_form.setText("变回超天酱" if ame else "切换成糖糖（素颜）")

    def _refresh_voice_action(self):
        if not hasattr(self, "_voice_actions"):
            return
        cur = self.tts.current_voice()
        for key, a in self._voice_actions.items():
            a.setChecked(key == cur)
            a.setEnabled(not self.a_voice_by_form.isChecked())

    def _pick_voice(self, key):
        """手动指定音色（会关掉「跟随形象」）。"""
        self.cfg["tts"]["voice_by_form"] = False
        self.cfg["tts"]["default_voice"] = key
        self.a_voice_by_form.setChecked(False)
        config.save_config(self.cfg)
        if self.tts.set_voice(key):
            self.tts.preload_voice(key)
        self._refresh_voice_action()
        self.preview_voice(key)

    def _toggle_voice_by_form(self, on):
        self.cfg["tts"]["voice_by_form"] = bool(on)
        config.save_config(self.cfg)
        self._sync_voice()
        self._refresh_voice_action()

    def preview_voice(self, key=None):
        self.tts.refresh_config()
        name = self.tts.voice_names().get(key or self.tts.current_voice(), "")
        self.bubble.show_text(f"「{name}」的声音哦", 1500)
        self._place_bubble()
        self.tts.speak(self.tts.demo_line(key), voice=key)

    def toggle_sleep(self):
        self.engine.toggle_sleep()
        self._refresh_sleep_action()
        self._refresh_form_action()

    # ---------------- 后台任务 ----------------
    def run_async(self, fn, on_done):
        thread = QThread(self)
        worker = Worker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(on_done)
        worker.done.connect(thread.quit)
        # Qt 官方模板：worker 在自己的线程里自删，线程结束后也自删。
        # 之前只接了 thread.finished -> worker.deleteLater，那时线程已经退出、
        # 事件循环没了，删除请求永远排不上，每问一句就漏一个 QThread。
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda w=worker: self._cleanup_worker(w))
        thread.finished.connect(lambda t=thread: self._cleanup_thread(t))
        # 持有 worker Python 引用，防止局部变量回收导致任务不执行
        self._workers.append(worker)
        self._threads.append(thread)
        thread.start()

    def _cleanup_thread(self, t):
        if t in self._threads:
            self._threads.remove(t)

    def _cleanup_worker(self, w):
        if w in self._workers:
            self._workers.remove(w)

    # ---------------- 对话流程 ----------------
    def open_chat(self):
        self._place_panel()
        if not self.chat_panel.isVisible():
            self.chat_panel.show()
            self.chat_panel.raise_()
        # 无记忆时给个开场
        if not self.llm.memory.messages:
            from .llm import parse_reply

            self.deliver_reply(parse_reply(persona.GREETING))

    def handle_user_text(self, text):
        if self.busy:
            return
        self.busy = True
        self._place_panel()
        self.chat_panel.show_waiting()
        self.engine.play_reaction(self.lib.pick_for_emotion("thinking", self.engine.current_form()), fps=8)
        self.run_async(lambda: self.llm.chat(text), self.on_reply)

    def on_reply(self, reply):
        self.busy = False
        self.deliver_reply(reply)

    def deliver_reply(self, reply):
        self.chat_panel.show_reply(reply)
        self._place_panel()
        emotion = reply.get("emotion", "neutral")
        # 必须带上当前形象：否则变成糖糖以后，情绪动作还是超天酱的动画
        anim = self.lib.pick_for_emotion(emotion, self.engine.current_form())
        self.engine.play_reaction(anim, fps=8)
        text = reply.get("text", "")
        if text and not text.startswith("（"):
            self.tts.speak(text)

    # ---------------- TTS ----------------
    def _on_tts_started(self):
        self.engine.notify_talking(True)

    def _on_tts_finished(self, _ok):
        if not self.tts.is_speaking():
            self.engine.notify_talking(False)

    # ---------------- 截屏 ----------------
    def manual_screen(self):
        if self.busy or not self.cfg["vision"]["enabled"]:
            return
        self.busy = True
        self.open_chat()
        self.chat_panel.show_waiting("让我看看你在干嘛哦～")

        def job():
            shot = vision.latest_or_capture(self.cfg["vision"])
            return self.llm.chat("阿宅君你看，这是我现在的屏幕哦～", image_path=shot)

        self.run_async(job, self.on_reply)

    def _arm_vision(self):
        mins = max(2, self.cfg["vision"]["interval_minutes"])
        self.vision_timer.start(mins * 60_000)

    def proactive_screen(self):
        if self.engine.is_sleeping():
            self._arm_vision()
            return
        if self.cfg["vision"]["enabled"] and self.cfg["vision"]["proactive_comment"]:
            if not self.busy:
                self.busy = True

                def job():
                    shot = vision.latest_or_capture(self.cfg["vision"])
                    return self.llm.chat(
                        "（你偷偷看了一眼阿宅君的屏幕）",
                        image_path=shot,
                        system_override=persona.SCREEN_PROMPT,
                    )

                def done(reply):
                    self.busy = False
                    self.deliver_reply(reply)

                self.run_async(job, done)
        self._arm_vision()

    # ---------------- 空闲搭话 ----------------
    def _arm_chitchat(self):
        self.chitchat_timer.start(random.randint(12, 28) * 60_000)

    def proactive_chitchat(self):
        if self.engine.is_sleeping():
            self._arm_chitchat()
            return
        if not self.busy and not self._speaking():
            self.busy = True
            topic = random.choice(persona.PROACTIVE_TOPICS)
            self.run_async(lambda: self.llm.raw_say(topic), self._chitchat_done)
        self._arm_chitchat()

    def _chitchat_done(self, reply):
        self.busy = False
        self.deliver_reply(reply)

    def _speaking(self):
        return self.tts.is_speaking()

    def open_log(self):
        """用系统默认程序打开运行日志（pythonw 下没有控制台，出问题要看这个）。"""
        path = logsetup.log_path()
        if not os.path.exists(path):
            QMessageBox.information(None, "超天酱", "还没有日志文件哦～")
            return
        try:
            os.startfile(path)
        except Exception as e:
            QMessageBox.warning(None, "超天酱", f"打不开日志：{e}\n\n{path}")

    # ---------------- 设置窗口 ----------------
    def open_settings(self):
        from .settings_dialog import SettingsDialog

        dlg = SettingsDialog(
            self.cfg,
            config.save_config,
            autostart_fn=self._apply_autostart,
            preview_fn=self.preview_voice,
            parent=self,
        )
        dlg.exec()
        self.tts.refresh_config()
        self.a_autostart.setChecked(autostart.is_enabled())
        self._sync_behavior_actions()
        self._sync_voice()
        self._refresh_voice_action()
        if (
            self.cfg["pet"].get("scale") != self.character.scale
            or self.cfg["pet"].get("fps") != self.character.fps
        ):
            QMessageBox.information(None, "超天酱", "大小或帧率改动需要重启桌宠才会生效哦～")

    def _sync_behavior_actions(self):
        b = self.cfg.get("behavior", {})
        self.a_roaming.setChecked(bool(b.get("roaming", True)))
        self.a_idle_act.setChecked(bool(b.get("idle_action", True)))
        self.a_inertia.setChecked(bool(b.get("drag_inertia", True)))
        self.a_sleep_sched.setChecked(bool(b.get("sleep_enabled", True)))
        self._refresh_form_action()
        self._refresh_voice_action()

    def _apply_autostart(self, on):
        try:
            autostart.set_autostart(on)
        except Exception as e:
            print("自启动设置失败:", e)

    # ---------------- 菜单动作 ----------------
    def clear_memory(self):
        if self.busy:
            return
        self.llm.memory.clear()
        self.chat_panel.hide()
        self.tray.showMessage(
            "超天酱", "记忆清空啦，重新认识一下吧♡", QIcon(os.path.join(config.ASSETS_DIR, "icon.ico")), 2000
        )

    def toggle_autostart(self):
        on = self.a_autostart.isChecked()
        try:
            autostart.set_autostart(on)
            self.cfg["autostart"] = on
            config.save_config(self.cfg)
            self.tray.showMessage(
                "超天酱",
                "好耶！开机就能见到我啦♡" if on else "呜诶…开机不陪我了吗…",
                QIcon(os.path.join(config.ASSETS_DIR, "icon.ico")),
                2000,
            )
        except PermissionError:
            QMessageBox.warning(None, "超天酱", "没有权限修改自启动，请用管理员身份运行。")
            self.a_autostart.setChecked(not on)

    def quit(self):
        self.engine.stop()
        self.vision_timer.stop()
        self.chitchat_timer.stop()
        self.tts.close()
        # 关闭 LLM HTTP 连接，避免退出时原生清理崩溃
        self.llm.close()
        pos = self.engine.current_pos()
        self.cfg["pet"]["pos"] = [pos.x(), pos.y()]
        config.save_config(self.cfg)
        self.bubble.hide()
        self.tray.hide()
        if self._exit_callback is not None:
            self._exit_callback()
        else:
            QApplication.quit()

    # ---------------- 鼠标交互 ----------------
    def _on_character(self, ev):
        """只有点到角色身上的不透明像素才算点中她。"""
        local = self.character.mapFrom(self, ev.position().toPoint())
        return self.character.hits(local)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            if not self._on_character(ev):
                ev.ignore()
                return
            self._press_global = ev.globalPosition().toPoint()
            self._dragging = False
        elif ev.button() == Qt.RightButton:
            if self._on_character(ev):
                self._show_menu(ev.globalPosition().toPoint())
            else:
                ev.ignore()

    def mouseMoveEvent(self, ev):
        if not (ev.buttons() & Qt.LeftButton):
            return
        gp = ev.globalPosition().toPoint()
        if not self._dragging:
            if (gp - self._press_global).manhattanLength() < 7:
                return
            self._dragging = True
            self.engine.on_press(self._press_global)
        self.engine.on_drag(gp)

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        if self._dragging:
            self.engine.on_release()
        else:
            self.engine.on_click()
        self._dragging = False

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._on_character(ev):
            self.open_chat()

    def _show_menu(self, pos):
        m = self.tray.contextMenu()
        self._refresh_sleep_action()
        m.exec(pos)
