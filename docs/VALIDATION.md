# v1.0.0 验证记录

验证日期：2026-10-04，Windows x64，Python 3.12.14 / PySide6 6.11.2。

| 检查 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests -v` | 11 项故障回归修复前均失败；修复后连同退出状态检查共 12 项通过 |
| `tools/test_behavior.py` | 走动、抛物理、睡眠、换形象、动画缓存通过 |
| `tools/test_regressions.py` | 对话去重、客户端更新、记忆恢复、截图清理、模拟播放与单实例通过 |
| `tools/test_settings_ui.py` | 设置布局、密码隐藏、总开关保留子项通过 |
| `ruff check --select F821,F822,F823,E9` / `compileall` | 通过 |
| 源码 `main.py --self-test ...` | 双形象、资源、睡眠、后台任务及线程清理通过 |
| 无 TTS EXE | 解压后中文路径启动、双形象、设置、睡眠与线程清理通过；未导入语音/音频/NumPy 模块 |
| 有 TTS EXE | 解压后中文路径启动、双形象、设置、睡眠与线程清理通过 |
| 真实 GPT-SoVITS 双音色 | 超天酱 5.46 秒、糖糖 3.84 秒，音频不同；不播放、不调用聊天 API |
| 发布包内容 | 不含密钥配置、聊天记录、日志、截图、训练原始文件；附 SHA-256 |

EXE 启动检查首次发现 DLL 符号缺失。Qt 的原始 DLL 哈希与源环境一致；定位到 PyInstaller 从构建环境 PATH 收集了 Poppler 的 `icuuc.dll`，缺少 Qt 所需的无后缀 ICU 导出。
排除该错误库并使用 Windows 系统 ICU 后，通过发布程序本身的 `--self-test` 验收。
有 TTS 版另复现一次退出阶段的原生访问异常；主入口在状态落盘、服务停止之后直接结束进程，避免进入有问题的原生库退出清理。
修复后有 TTS EXE 连续三轮启动/退出均返回 0，其中一轮使用实际 Windows 窗口平台，另外两轮使用 offscreen。

界面自动验收使用 Qt offscreen，并只渲染应用自身窗口，不截取用户桌面。
大模型付费聊天与视觉请求没有实网调用；这两部分使用离线模拟覆盖请求构造与故障降级。
有 TTS 包包含四个权重及两个参考 WAV，需另行安装 GPT-SoVITS v2ProPlus 推理后端。
