# -*- coding: utf-8 -*-
"""检查设置窗口（「桌宠行为」分组）的排版与总开关行为。

运行：.venv\\Scripts\\python.exe tools\\test_settings_ui.py
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QLineEdit
from pet.config import load_config
from pet.settings_dialog import SettingsDialog

app = QApplication.instance() or QApplication(sys.argv)
cfg = load_config()
# 用捕获式的 save：测试绝不能把改动真的写进 data/config.json
saved = {}
dlg = SettingsDialog(cfg, lambda c: saved.update(cfg=c))
dlg.show()
app.processEvents()

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "settings_dialog.png")
dlg.grab().save(out)
print("设置窗口尺寸:", dlg.size())
print("行为分组存在:", hasattr(dlg, "roaming"), hasattr(dlg, "sleep_form"))
assert dlg.api_key.echoMode() == QLineEdit.EchoMode.Password, "API Key 输入框必须隐藏"
assert dlg.vision_api_key.echoMode() == QLineEdit.EchoMode.Password, "视觉 Key 输入框必须隐藏"
print("读到的值: 走动=%s 速度=%s 惯性=%s 睡觉=%s %s~%s 形态=%s" % (
    dlg.roaming.isChecked(), dlg.walk_speed.value(), dlg.drag_inertia.isChecked(),
    dlg.sleep_enabled.isChecked(), dlg.sleep_start.time().toString("HH:mm"),
    dlg.sleep_end.time().toString("HH:mm"), dlg.sleep_form.currentData()))
print("截图:", out)

# ---------------------------------------------------------------- 总开关
# 回归：以前 on_save 会写 roaming = 勾选 and 总开关，把用户勾好的子项
# 直接落盘成 False，重新打开总开关时它们不会自己回来。
print("\n--- 桌宠行为总开关 ---")
before = (dlg.roaming.isChecked(), dlg.idle_action.isChecked())
dlg.behavior_enabled.setChecked(False)
disabled = (not dlg.roaming.isEnabled() and not dlg.drag_inertia.isEnabled()
            and not dlg.sleep_enabled.isEnabled())
print("关掉总开关后子项置灰:", disabled)
assert disabled, "总开关关闭时子项应该置灰"

dlg.on_save()
b = saved["cfg"]["behavior"]
print("写入 enabled=%s roaming=%s idle_action=%s"
      % (b["enabled"], b["roaming"], b["idle_action"]))
assert b["enabled"] is False, "总开关本身应该写进配置"
assert (b["roaming"], b["idle_action"]) == before, "关闭总开关不能抹掉子项的勾选"

dlg.behavior_enabled.setChecked(True)
print("重新打开总开关后子项可点:", dlg.roaming.isEnabled())
assert dlg.roaming.isEnabled(), "重新打开总开关后子项应恢复可点"
assert (dlg.roaming.isChecked(), dlg.idle_action.isChecked()) == before, "子项勾选应保持不变"

print("\n全部通过 ✔")
