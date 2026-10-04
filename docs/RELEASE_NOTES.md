# 超天酱/糖糖桌宠 v1.0.0

Windows x64，解压整个文件夹后双击 EXE，无需安装 Python。

| 附件 | 内容 |
| --- | --- |
| `KangelAmePet-1.0.0-NoTTS-Windows-x64.zip` | 无 TTS 版：双形象、动画、聊天、记忆、行为，无语音依赖与权重 |
| `KangelAmePet-1.0.0-TTS-Windows-x64.zip` | 有 TTS 版：上述功能 + GPT-SoVITS 客户端、超天酱/糖糖双音色权重与参考音频 |
| `SHA256SUMS.txt` | 两个压缩包的 SHA-256 校验值 |

有 TTS 版**需要单独安装 GPT-SoVITS v2ProPlus 后端及基础预训练模型**；后端的 CUDA/PyTorch 环境没有包含在压缩包里。
在设置中填写后端目录（应包含 `api_v2.py` 和 `runtime/python.exe`），或配置已经运行的兼容 API。
权重路径由 API 服务端读取，远程 API 需让服务端也能访问相同的权重和参考音频路径。

首次启动请打开“设置”填写自己的大模型 API Key；截屏默认关闭，可按需开启。
运行数据保存在 `%LOCALAPPDATA%/KangelAmePet/tts` 或 `no_tts`，两版互不覆盖。
压缩包与公开源码不包含本地密钥、聊天记录、截图或训练原始数据。

修复配置/记忆恢复、停止音频、关闭配音后的预热、音色加载失败状态、打包路径、自启及重复启动问题。
完整改动与验证记录见仓库 `docs/CHANGELOG.md`、`docs/VALIDATION.md`。

游戏图像及角色版权归 WSS playground / why so serious 所有；语音权重来自原项目使用的 K&A TTS。
