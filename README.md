# 超天酱/糖糖桌宠

Windows 桌面宠物：超天酱（KAngel）与糖糖（Ame）双形象，透明置顶、动画、走动、拖拽惯性、夜间睡眠、AI 对话及本地记忆。

## 下载与启动

在 [Releases](https://github.com/tszmzz1026/kangel-ame-desktop-pet/releases) 下载其中一版，**完整解压**后双击文件夹里的 EXE。无需安装 Python，不能只复制 EXE。

| 版本 | 包含内容 |
| --- | --- |
| 无 TTS | 双形象、动画、行为、对话、视觉与记忆；不包含语音依赖或模型 |
| 有 TTS | 所有桌宠功能、语音客户端，以及超天酱/糖糖两套 GPT/SoVITS 权重与参考音频；**GPT-SoVITS 后端另装** |

首次运行：右键角色或托盘 → 设置 → 填自己的接口地址、API Key、模型 → 保存 → 双击角色聊天。
角色台词为日语，附中文翻译和推荐回复。未配置 API 时，动画与行为仍可使用。

## TTS 配置

1. 从 [GPT-SoVITS 官方仓库](https://github.com/RVC-Boss/GPT-SoVITS) 获取兼容 v2ProPlus 的 Windows 整合环境和基础预训练模型。
2. 在设置中填写“GPT-SoVITS 后端目录”，该目录应包含 `api_v2.py` 和 `runtime/python.exe`。
3. “双音色模型根目录”默认指向发布包旁的 `tts_models`，不用移动里面的文件。
4. 勾选“启用 AI 配音”，保存后点击“试听”；默认音色跟随角色形象。

也可连接已启动的 GPT-SoVITS `api_v2` 服务，在设置中填写 TTS API 地址。
远程服务需要在**服务端**放置权重和参考音频，并在配置中使用服务端能够读取的路径。
有 TTS 包没有附带 CUDA、PyTorch 与通用推理环境；仅下载本包不能独立完成语音推理。

## 操作

| 操作 | 效果 |
| --- | --- |
| 单击 / 双击角色 | 动作反应 / 打开聊天 |
| 拖动后松手 | 移动、惯性抛出、落地弹跳 |
| 右键角色或托盘 | 设置、换形象、行为、睡眠、自启、退出 |
| 设置中的截屏开关 | 允许手动或自动观察屏幕，默认关闭 |

截图会发送至配置的视觉 API，仅保留最近 5 张。未启用截屏时，手动菜单不会抓图。
[DeepSeek 官方文档](https://api-docs.deepseek.com/quick_start/pricing/) 当前使用 `deepseek-flash` 名称；其他预设与模型可自行按服务商文档调整。

## 数据与隐私

发布版将配置、记忆和日志保存在 `%LOCALAPPDATA%/KangelAmePet/tts` 或 `no_tts`，两版独立。
源码版使用项目 `data/`，可用 `PET_DATA_DIR` 指定其他目录。配置中的 Key 只写入本机，发行附件与仓库不带个人数据。
配置与记忆原子保存，读取损坏配置时保留原文件，日志可通过托盘打开。

可选环境变量：`PET_DATA_DIR`、`PET_API_KEY`、`TTS_API_URL`、`SOVITS_DIR`、`KA_TTS_DIR`。

## 从源码运行

Python 3.10+，Windows x64。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

也可双击 `启动桌宠.bat`；首次先按上述命令安装环境。`调试模式.bat` 保留控制台。

## 测试与打包

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools\test_behavior.py
.\.venv\Scripts\python.exe tools\test_regressions.py
.\.venv\Scripts\python.exe tools\test_settings_ui.py
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe scripts\build_release.py --variant all --model-root "双音色模型根目录"
```

构建时不传 `--model-root` 会生成不附权重的 TTS 客户端包；本次发布的有 TTS 附件包含两套权重。
可重复运行的打包验收入口：`main.py --self-test 报告路径` 或 `EXE --self-test 报告路径`。
验收只渲染桌宠自己的窗口，不联网、不截取桌面、不启动 TTS 后端。

目录：`pet/` 应用代码，`assets/` 动画，`tests/` 回归，`scripts/` 构建发布，`docs/` 改动与验证记录。
源码保留原项目的包结构，避免破坏既有导入与工具。

## 素材来源

角色与图像来自《主播女孩重度依赖 / NEEDY STREAMER OVERLOAD》，版权归 WSS playground / why so serious 所有。
语音权重来自原项目使用的 K&A TTS 微调模型。本项目为非官方桌宠，保留原素材权利声明。
