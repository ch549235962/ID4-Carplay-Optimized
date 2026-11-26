# 部署到已有环境

## 前置条件

- Apple Silicon Mac、Python 3.13、Node.js 和 Apple Command Line Tools。当前启动器默认使用 `/opt/homebrew/bin/python3.13` 与 Homebrew Node。
- 已能启动的原始 HU_NBT / QNX 6.5 x86 本地环境；工作区中已有 `NBT-Original`、`NBT-Dev`、`NBT-Dev-Cross`。
- 已有 `zh-CN-carplay-load` 基础配置和可用的本地 QNX 交叉编译环境、FFmpeg 静态库。原厂 HMI 和固件由使用者自行提供。
- `/Applications/MacPlay.app` 版本 1.2.4。先运行原软件一次，完成个人配置与 USB 测试；本项目不会获取、上传或替换认证文件。
- 对所使用的上游模拟器源码及任何本地适配拥有必要授权。仓库不附带上游受限源码。

## 安装与编译

先关闭当前运行的本地服务，再执行。`deploy.py` 会备份被覆盖的源码；图形集成工具也会备份目标文件。

```sh
python3 deploy.py --workspace /path/to/outputs --dry-run
python3 deploy.py --workspace /path/to/outputs
python3 integration/apply_local_graphics.py --workspace /path/to/outputs --dry-run
python3 integration/apply_local_graphics.py --workspace /path/to/outputs

python3 /path/to/outputs/NBT-Dev-Cross/tools/linux_vm.py start
python3 /path/to/outputs/CarPlay-QNX-Native/tools/build_native_hid.py
python3 /path/to/outputs/CarPlay-QNX-Native/tools/build_native_display_bridge.py
python3 /path/to/outputs/CarPlay-QNX-Native/tools/build_native_video.py
python3 /path/to/outputs/NBT-Original/tools/build_renderer.py
python3 /path/to/outputs/CarPlay-QNX-Native/tools/prepare_nbt_native.py
python3 /path/to/outputs/NBT-Launcher/build.py
```

`build_renderer.py` 沿用现有本地图形环境；它以及授权的 ANGLE 库、基础镜像重打包工具需已存在于工作区。编译桥接扩展时读取你本地的上游源码，不会将它复制到本 Git 仓库。旧版编译器需保留 `-march=pentium4`，否则原子操作可能生成 QNX 无法解析的辅助符号。

启动前确认 `NBT-Original/vm/selected-profile.json` 中的 `language` 是 `zh-CN-carplay-native`。首次设置可在已停止的工作区中把该文件写为：

```json
{"language":"zh-CN-carplay-native"}
```

固件中会放入你工作区已有的本地 SSH 主机密钥和授权公钥。这些文件必须由你自己生成并保管，不能提交到公开仓库。仅对本机回环端口 `2225` 开放 guest SSH。

## 日常使用

- 连接 iPhone USB 数据线，双击桌面“NBT CarPlay 启动器”。接收服务先开启，QNX 继续初始化。
- 网页由“打开 NBT 网页”和“打开 CarPlay 状态页”两个按钮手动打开。
- “重新连接 CarPlay”重启接收端并保留虚拟机；“全部停止”同时关闭监护和所有项目服务。
- 关闭控制台窗口会保留后台服务。
- 不要同时启动独立 MacPlay 接收端和本项目接收端。

## 无线测试

无线 CarPlay 使用蓝牙发现/认证，视频与音频通过 Wi-Fi。它不是只用蓝牙传画面。

在工作区 `CarPlay-Wireless/config-private.json` 保存你自己的配置；这个文件不能入 Git：

```json
{"bt_address":"00:11:22:33:44:55","wifi_ssid":"YOUR_WIFI","wifi_passphrase":"YOUR_PASSWORD","wifi_channel":48}
```

以上值是占位示例。手机先与 Mac 配对；两端接入允许互访的 Wi-Fi。程序读取当前 Mac 的真实蓝牙地址和当前信道。SSID 因定位权限不可读时保留你明确填写的名称，不会自动读取钥匙串密码或抹掉手机配对。

```sh
python3 /path/to/outputs/MacPlay-NBT/tools/macplay_nbt.py wireless-check
```

准备测试时拔掉 iPhone USB，再点“无线 CarPlay 测试”；只有收到非 USB 接口上的真实手机视频才算无线通过。随时用“切回 USB”恢复有线。当前实测状态见 VALIDATION.md。

## 帧率配置与 60 FPS 试验

仅用于本地模拟器，不会更改实车安装包。先在桌面启动器点击“全部停止”，再执行：

```sh
python3 /path/to/outputs/NBT-Original/tools/video_profile.py --fps 60
```

随后点击“全部开启”，并刷新已打开的 NBT 网页。该模式向手机请求 60 FPS，将网页取帧间隔改为约 16.7 ms；CPU 仍为 `qemu32` / 1 vCPU、内存仍为 512 MiB，保留原先的固定 `icount` 时钟。

**该 60 FPS 模式尚未通过稳定性验证，不作为默认配置。** 2026-11-27 的尝试未实现稳定 60 FPS，当前本机已回退到 30 FPS 请求，见验证记录。静止页面会减少视频帧，网页取帧频率也不等于显示器刷新率。

恢复默认帧率：先点击“全部停止”，执行下列命令，再开启服务：

```sh
python3 /path/to/outputs/NBT-Original/tools/video_profile.py --fps 30
```

用持续画面变化测量实际速率（`--drive` 会往返旋转焦点，不进行选择）：

```sh
python3 /path/to/outputs/CarPlay-QNX-Native/tools/verify_frame_rate.py --seconds 20 --drive --label video-rate
```

测量在窗口起止直接读取 QNX 共享内存计数，以 Mac 单调时钟计时；若解码重启、HMI 退出或显示不再推进，报告标为无效，不会把解码率或请求值当成成功显示帧率。

## 验证与回退

```sh
node --test runtime/MacPlay-NBT/tools/avc.test.cjs runtime/MacPlay-NBT/tools/bridge_recovery.test.cjs
python3 /path/to/outputs/MacPlay-NBT/tools/verify_startup.py --cold
python3 /path/to/outputs/MacPlay-NBT/tools/verify_recovery.py
python3 /path/to/outputs/CarPlay-QNX-Native/tools/verify_display_performance.py
```

后面三项是有实际副作用的本地验收：会重启测试 VM、终止本项目拥有的视频/接收进程，或发送成对旋钮动作。不要在需要保持当前手机会话的时刻执行。

回退时先点“全部停止”，从工作区 `.id4-backups/` 恢复被覆盖的源码，使用你保留的原启动镜像及原渲染器。这里的性能与调度调整仅用于模拟器，不要直接复制到真实车机。真实 NBT 重启按上游 ZGW 流程操作，不运行 `/sbin/shutdown`。
