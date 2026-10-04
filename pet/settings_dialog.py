# -*- coding: utf-8 -*-
"""设置窗口：可视化填写 API Key、模型、视觉、配音等，无需手改 config.json。"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QGroupBox,
    QComboBox,
    QTimeEdit,
    QScrollArea,
    QWidget,
    QFrame,
)
from PySide6.QtCore import QTime, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from .build_info import TTS_AVAILABLE

STYLE = """
QDialog { background: #fff7fc; }
QScrollArea, QScrollArea > QWidget > QWidget { background: #fff7fc; border: none; }
QGroupBox {
    font-weight:bold; color:#d6539a; border:1.5px solid #ffb9dd;
    border-radius:12px; margin-top:12px; padding:8px; background:#fffafd;}
QGroupBox::title { subcontrol-origin: margin; left:12px; padding:0 4px;}
QLineEdit { border:1.5px solid #ffc2e2; border-radius:8px; padding:6px; background:#fff;}
QLineEdit:focus { border-color:#ff7fc0;}
QPushButton { border-radius:10px; padding:7px;}
QPushButton#Save { background:#ff7fc0; color:#fff; font-weight:bold; border:none;}
QPushButton#Save:hover { background:#ff5fb0;}
QPushButton#Preset { background:#fff; border:1.5px solid #ffb3dd; color:#b03a78;}
QPushButton#Preset:hover { background:#ffe3f2;}
"""

PRESETS = {
    "DeepSeek(对话+视觉)": dict(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-flash",
        vision_model="deepseek-flash",
        vision_base_url="",
        vision_api_key="",
    ),
    "智谱(对话+视觉)": dict(
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-flash",
        vision_model="glm-4v-flash",
        vision_base_url="",
        vision_api_key="",
    ),
    "DeepSeek+智谱视觉": dict(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-flash",
        vision_model="glm-4v-flash",
        vision_base_url="https://open.bigmodel.cn/api/paas/v4",
        vision_api_key="",
    ),
    "通义千问": dict(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        vision_model="qwen-vl-plus",
        vision_base_url="",
        vision_api_key="",
    ),
}


class SettingsDialog(QDialog):
    def __init__(self, cfg, save_fn, autostart_fn=None, preview_fn=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("超天酱设置")
        self.setMinimumWidth(500)
        self.setStyleSheet(STYLE)
        self.cfg = cfg
        self.save_fn = save_fn
        self.autostart_fn = autostart_fn
        self.preview_fn = preview_fn

        # 内容放进滚动区：小屏笔记本上也能完整看到所有设置
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self._content = content
        lay = QVBoxLayout(content)
        lay.setContentsMargins(14, 12, 14, 12)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("快捷预设："))
        for name in PRESETS:
            b = QPushButton(name)
            b.setObjectName("Preset")
            b.clicked.connect(lambda _=False, n=name: self.apply_preset(n))
            preset_row.addWidget(b)
        lay.addLayout(preset_row)

        # 对话
        g1 = QGroupBox("对话大模型")
        f1 = QFormLayout(g1)
        self.base_url = QLineEdit()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.model = QLineEdit()
        f1.addRow("接口地址 base_url", self.base_url)
        f1.addRow("API Key", self.api_key)
        f1.addRow("模型 model", self.model)
        lay.addWidget(g1)

        # 视觉
        g2 = QGroupBox("截屏视觉（不填视觉模型则只截屏、不评论）")
        f2 = QFormLayout(g2)
        self.vision_model = QLineEdit()
        self.vision_base_url = QLineEdit()
        self.vision_api_key = QLineEdit()
        self.vision_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        f2.addRow("视觉模型", self.vision_model)
        f2.addRow("视觉接口地址（留空用上面）", self.vision_base_url)
        f2.addRow("视觉 Key（留空用上面）", self.vision_api_key)
        self.vision_enabled = QCheckBox("允许截屏")
        self.proactive = QCheckBox("允许定时自动偷看")
        self.interval = QSpinBox()
        self.interval.setRange(2, 180)
        self.interval.setSuffix(" 分钟")
        vrow = QHBoxLayout()
        vrow.addWidget(self.vision_enabled)
        vrow.addWidget(self.proactive)
        vrow.addWidget(self.interval)
        f2.addRow(vrow)
        lay.addWidget(g2)

        # 桌宠行为
        g4 = QGroupBox("桌宠行为（走动 / 拖拽惯性 / 空闲小动作 / 夜间睡觉）")
        f4 = QFormLayout(g4)
        self.behavior_enabled = QCheckBox("启用自己的小动作与走动")
        self.behavior_enabled.toggled.connect(self._sync_behavior_enabled)
        f4.addRow(self.behavior_enabled)

        self.roaming = QCheckBox("在桌面上走来走去")
        self.walk_speed = QSpinBox()
        self.walk_speed.setRange(10, 400)
        self.walk_speed.setSuffix(" 像素/秒")
        wrow = QHBoxLayout()
        wrow.addWidget(self.roaming)
        wrow.addWidget(self.walk_speed)
        f4.addRow(wrow)

        self.idle_action = QCheckBox("空闲时随机做小动作")
        self.idle_min = QSpinBox()
        self.idle_min.setRange(3, 600)
        self.idle_min.setSuffix(" 秒")
        self.idle_max = QSpinBox()
        self.idle_max.setRange(3, 1200)
        self.idle_max.setSuffix(" 秒")
        irow = QHBoxLayout()
        irow.addWidget(self.idle_action)
        irow.addWidget(QLabel("间隔"))
        irow.addWidget(self.idle_min)
        irow.addWidget(QLabel("～"))
        irow.addWidget(self.idle_max)
        f4.addRow(irow)

        self.drag_inertia = QCheckBox("拖拽松手后带惯性甩出、落地弹跳")
        f4.addRow(self.drag_inertia)

        self.sleep_enabled = QCheckBox("夜里自动睡觉（睡觉时不主动搭话、不看屏幕）")
        self.sleep_start = QTimeEdit()
        self.sleep_start.setDisplayFormat("HH:mm")
        self.sleep_end = QTimeEdit()
        self.sleep_end.setDisplayFormat("HH:mm")
        srow = QHBoxLayout()
        srow.addWidget(self.sleep_enabled)
        srow.addWidget(QLabel("从"))
        srow.addWidget(self.sleep_start)
        srow.addWidget(QLabel("到"))
        srow.addWidget(self.sleep_end)
        f4.addRow(srow)

        self.sleep_form = QComboBox()
        self.sleep_form.addItem("雨ちゃん（素颜）", "ame")
        self.sleep_form.addItem("超天酱（直播形象）", "cho")
        f4.addRow("睡觉时的样子", self.sleep_form)
        lay.addWidget(g4)

        # 配音/其他
        g3 = QGroupBox("配音与其他")
        f3 = QFormLayout(g3)
        self.tts_enabled = QCheckBox("启用 AI 配音")
        self.tts_enabled.setEnabled(TTS_AVAILABLE)
        if not TTS_AVAILABLE:
            self.tts_enabled.setText("本版本不包含 TTS")
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 2.0)
        self.speed.setSingleStep(0.05)
        f3.addRow(self.tts_enabled)
        f3.addRow("语速", self.speed)
        self.tts_api_url = QLineEdit()
        self.sovits_dir = QLineEdit()
        self.ka_tts_dir = QLineEdit()
        if TTS_AVAILABLE:
            f3.addRow("TTS API 地址", self.tts_api_url)
            f3.addRow("GPT-SoVITS 后端目录", self.sovits_dir)
            f3.addRow("双音色模型根目录", self.ka_tts_dir)
        self.speed.setEnabled(TTS_AVAILABLE)

        self.voice_by_form = QCheckBox("音色跟随形象（超天酱 / 糖糖）")
        self.voice_by_form.toggled.connect(self._sync_voice_enabled)
        f3.addRow(self.voice_by_form)
        vrow = QHBoxLayout()
        self.voice_combo = QComboBox()
        self.voice_preview = QPushButton("试听")
        self.voice_preview.setObjectName("Preset")
        self.voice_preview.clicked.connect(self.on_preview)
        vrow.addWidget(QLabel("音色"))
        vrow.addWidget(self.voice_combo, 1)
        vrow.addWidget(self.voice_preview)
        f3.addRow(vrow)
        if not TTS_AVAILABLE:
            self.voice_by_form.hide()
            self.voice_combo.hide()
            self.voice_preview.hide()
        self.voice_hint = QLabel("")
        self.voice_hint.setStyleSheet("color:#a08a97; font-size:11px;")
        self.voice_hint.setWordWrap(True)
        f3.addRow(self.voice_hint)

        self.autostart = QCheckBox("开机自启动")
        f3.addRow(self.autostart)
        lay.addWidget(g3)

        self.save_btn = QPushButton("保存设置")
        self.save_btn.setObjectName("Save")
        self.save_btn.clicked.connect(self.on_save)
        outer.addWidget(self.save_btn)

        self.load_values()
        self._fitted = False

    def showEvent(self, ev):
        """布局算完后再定窗口高度：小屏自动变滚动，大屏一次显示完。"""
        super().showEvent(ev)
        if not self._fitted:
            self._fitted = True
            # 延后一轮事件循环，等布局把真实高度算出来再定尺寸
            QTimer.singleShot(0, self._fit_to_screen)

    def _fit_to_screen(self):
        """高度按内容算，但不超过屏幕可用高度（超出的部分靠滚动看）。"""
        lay = self._content.layout()
        if lay is not None:
            lay.activate()
        self._content.adjustSize()
        want_h = self._content.sizeHint().height() + self.save_btn.sizeHint().height() + 40
        want_w = max(520, self._content.sizeHint().width() + 30)
        scr = QGuiApplication.primaryScreen()
        limit = (scr.availableGeometry().height() - 70) if scr else want_h
        self.resize(want_w, max(420, min(want_h, limit)))

    def load_values(self):
        c = self.cfg["llm"]
        self.base_url.setText(c.get("base_url", ""))
        self.api_key.setText(c.get("api_key", ""))
        self.model.setText(c.get("model", ""))
        self.vision_model.setText(c.get("vision_model", ""))
        self.vision_base_url.setText(c.get("vision_base_url", ""))
        self.vision_api_key.setText(c.get("vision_api_key", ""))
        v = self.cfg["vision"]
        self.vision_enabled.setChecked(v.get("enabled", True))
        self.proactive.setChecked(v.get("proactive_comment", True))
        self.interval.setValue(v.get("interval_minutes", 12))
        t = self.cfg["tts"]
        self.tts_enabled.setChecked(TTS_AVAILABLE and t.get("enabled", True))
        self.tts_api_url.setText(t.get("api_url", ""))
        self.sovits_dir.setText(t.get("sovits_dir", ""))
        self.ka_tts_dir.setText(t.get("ka_tts_dir", ""))
        self.speed.setValue(t.get("speed", 1.0))
        self.voice_by_form.setChecked(bool(t.get("voice_by_form", True)))

        # 音色下拉：来自 K&A TTS 的微调模型
        self.voice_combo.clear()
        models = t.get("models") or {}
        if models:
            for key, m in models.items():
                self.voice_combo.addItem(m.get("name") or key, key)
            idx = self.voice_combo.findData(t.get("default_voice") or "cho")
            self.voice_combo.setCurrentIndex(idx if idx >= 0 else 0)
            names = "、".join((m.get("name") or k) for k, m in models.items())
            self.voice_hint.setText(
                f"已接入 {len(models)} 个微调音色：{names}。"
                "勾选「音色跟随形象」后，超天酱说超天酱的声音、糖糖说糖糖的声音。"
            )
        else:
            self.voice_combo.addItem("（未配置 models，使用 config.json 里的参考音频）", "")
            self.voice_combo.setEnabled(False)
            self.voice_preview.setEnabled(False)
            self.voice_hint.setText(
                "要使用微调音色，请在 config.json 的 tts.models 里填写 GPT/SoVITS 权重与参考音频。"
            )
        self._sync_voice_enabled()

        self.autostart.setChecked(self.cfg.get("autostart", False))

        b = self.cfg.get("behavior", {})
        self.behavior_enabled.setChecked(b.get("enabled", True))
        self.roaming.setChecked(b.get("roaming", True))
        self.walk_speed.setValue(int(b.get("walk_speed", 55)))
        self.idle_action.setChecked(b.get("idle_action", True))
        self.idle_min.setValue(int(b.get("idle_action_min", 20)))
        self.idle_max.setValue(int(b.get("idle_action_max", 65)))
        self.drag_inertia.setChecked(b.get("drag_inertia", True))
        self.sleep_enabled.setChecked(b.get("sleep_enabled", True))
        self.sleep_start.setTime(self._parse_time(b.get("sleep_start", "23:30")))
        self.sleep_end.setTime(self._parse_time(b.get("sleep_end", "07:00")))
        idx = self.sleep_form.findData(b.get("sleep_form", "ame"))
        self.sleep_form.setCurrentIndex(idx if idx >= 0 else 0)
        self._sync_behavior_enabled()

    @staticmethod
    def _parse_time(s):
        try:
            h, m = [int(x) for x in str(s).split(":")]
            return QTime(h % 24, m % 60)
        except Exception:
            return QTime(23, 30)

    def _sync_voice_enabled(self):
        manual = not self.voice_by_form.isChecked()
        self.voice_combo.setEnabled(manual and bool(self.voice_combo.count()))

    def _sync_behavior_enabled(self):
        """总开关关掉时，把从属于它的选项置灰（保留用户原来的勾选）。"""
        on = self.behavior_enabled.isChecked()
        for w in (
            self.roaming,
            self.walk_speed,
            self.idle_action,
            self.idle_min,
            self.idle_max,
            self.drag_inertia,
            self.sleep_enabled,
            self.sleep_start,
            self.sleep_end,
            self.sleep_form,
        ):
            w.setEnabled(on)

    def on_preview(self):
        """试听：把当前设置先写回配置，再让桌宠用这个音色说一句。"""
        if not self.preview_fn:
            return
        self._write_tts()
        key = self.voice_combo.currentData() or None
        self.preview_fn(key)

    def _write_tts(self):
        """把音色相关设置写回配置（试听与保存都要用）。"""
        t = self.cfg["tts"]
        t["enabled"] = TTS_AVAILABLE and self.tts_enabled.isChecked()
        t["speed"] = self.speed.value()
        t["api_url"] = self.tts_api_url.text().strip()
        t["sovits_dir"] = self.sovits_dir.text().strip()
        t["ka_tts_dir"] = self.ka_tts_dir.text().strip()
        t["voice_by_form"] = self.voice_by_form.isChecked()
        key = self.voice_combo.currentData()
        if key:
            t["default_voice"] = key

    def apply_preset(self, name):
        p = PRESETS[name]
        self.base_url.setText(p["base_url"])
        self.model.setText(p["model"])
        self.vision_model.setText(p["vision_model"])
        self.vision_base_url.setText(p["vision_base_url"])
        self.vision_api_key.setText(p["vision_api_key"])

    def on_save(self):
        c = self.cfg["llm"]
        c["base_url"] = self.base_url.text().strip()
        c["api_key"] = self.api_key.text().strip()
        c["model"] = self.model.text().strip()
        c["vision_model"] = self.vision_model.text().strip()
        c["vision_base_url"] = self.vision_base_url.text().strip()
        c["vision_api_key"] = self.vision_api_key.text().strip()
        v = self.cfg["vision"]
        v["enabled"] = self.vision_enabled.isChecked()
        v["proactive_comment"] = self.proactive.isChecked()
        v["interval_minutes"] = self.interval.value()
        t = self.cfg["tts"]
        t["enabled"] = TTS_AVAILABLE and self.tts_enabled.isChecked()
        t["speed"] = self.speed.value()
        self._write_tts()
        b = self.cfg.setdefault("behavior", {})
        b["enabled"] = self.behavior_enabled.isChecked()
        # 不要在这里 and 上总开关：那会把用户勾好的子项直接落盘成 False，
        # 下次把总开关打开时它们不会自己回来。总开关由 BehaviorEngine 统一把关。
        b["roaming"] = self.roaming.isChecked()
        b["walk_speed"] = self.walk_speed.value()
        b["idle_action"] = self.idle_action.isChecked()
        lo, hi = self.idle_min.value(), self.idle_max.value()
        b["idle_action_min"] = min(lo, hi)
        b["idle_action_max"] = max(lo, hi)
        b["drag_inertia"] = self.drag_inertia.isChecked()
        b["sleep_enabled"] = self.sleep_enabled.isChecked()
        b["sleep_start"] = self.sleep_start.time().toString("HH:mm")
        b["sleep_end"] = self.sleep_end.time().toString("HH:mm")
        b["sleep_form"] = self.sleep_form.currentData()
        want_autostart = self.autostart.isChecked()
        self.cfg["autostart"] = want_autostart
        if self.autostart_fn:
            self.autostart_fn(want_autostart)
        self.save_fn(self.cfg)
        self.accept()
