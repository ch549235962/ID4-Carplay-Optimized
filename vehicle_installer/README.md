# ID4 CarPlay 实车安装器

macOS 和 Windows 中文桌面程序，用 ENET / SSH 给**原始 HU_NBT（QNX 6.5 x86，通常称 ID4）**安装 JayJay3071 原车 CarPlay 插件。它不刷整套 BMW 固件，也不安装本仓库的模拟器显示桥接或 MacPlay。

**当前为实验版：安装、备份和故障恢复经过隔离文件系统测试，尚未在真实车辆上验证。**

## 下载与使用

当前源码为 0.2.1，固定上游预发布版 v2026.11.26。Windows 最新构建见 [GitHub Actions](https://github.com/ch549235962/ID4-Carplay-Optimized/actions/workflows/build-vehicle-installer.yml)。旧版 0.2.0 仍可在 [v0.2.0 发布页](https://github.com/ch549235962/ID4-Carplay-Optimized/releases/tag/v0.2.0) 下载：

| 电脑 | 文件 |
|---|---|
| macOS 26+ / Apple Silicon | `ID4-CarPlay-macOS-AppleSilicon.zip`，解压后打开 `.app` |
| Windows 10/11 x64 | `ID4-CarPlay-Installer.exe`，直接运行 |

程序自带 Python、图形界面和 SSH 依赖，无需安装开发环境。Mac 包在 macOS 26 Apple Silicon 上构建和自检，所含 Tcl 库最低要求 macOS 26；较旧 macOS 或 Intel Mac 可按下文在本机从源码构建。

1. 用 **ENET 线**连接车辆和电脑，保持车辆稳定供电。Mac 没有网口时需要 USB 网卡。
2. 打开程序，输入车机地址（默认 `169.254.199.99`）和 **root SSH 密码**。可以先点“只检查连接”。
3. 点“**一键安装并重启**”，等待传输和逐文件校验完成。车辆网关接受请求后会重启 iDrive；未找到网关时，程序会提示手动重启。

**SSH 必须事先开通，且你必须有 root 密码。安装器不能自动解锁 SSH，也不能凭空生成密码。** CIC、NBT Evo、ID5/ID6 不支持；前置检查不通过就停止。

两个平台的程序都未做商业发行签名或公证。Mac 使用临时签名；首次打开时系统可能拦截，可按 macOS 的“隐私与安全性”提示处理该应用。Windows 也可能显示未知发布者。不要全局关闭系统安全保护。发布页提供 SHA-256 校验值和源码。

首次安装需要电脑联网下载约 2 MB 的固定官方 ZIP；电脑直连 ENET 后若无互联网，可以提前下载 [JayJay 官方 v2026.11.26](https://github.com/JayJay3071/nbt-android-auto/releases/tag/v2026.11.26)，在高级选项选择 `NBT-AndroidAuto-Python-2026.11.26.zip`。其他版本不会通过校验。

新版已包含上游的 USB 断开清理、配对记录持久化及蓝牙／USB 音频顺序修复；上游的首次配对优化仍标注未经实车验证。SSH 开通的补充参考见[上游说明](https://github.com/JayJay3071/nbt-android-auto/blob/3d1a4164e7b58b519f65149d558fb72983a5e6e3/README.md#ssh)。

安装完成后，按上游说明连接 iPhone 到车辆 USB，允许信任和 CarPlay；首次可能需要 2–3 分钟。这里没有承诺增加原主机不具备的无线 CarPlay 能力，也不更改车辆蓝牙固件。

## 安装内容与设置

只更新这两个插件目录及安装器自己的事务目录：

```text
/var/opt/hmi/data/rw/NbtAndroidAutoRT
/var/opt/hmi/data/rw/Plugins/NbtAndroidAuto
/var/opt/hmi/data/rw/.ID4CarPlayInstaller
```

固定上游版本 `v2026.11.26`，官方 ZIP SHA-256：

```text
2676a8057871463d28c8fe136ba17e34642247d9b37bbd86aa03453d4fd8430a
```

安装器验证整个 ZIP 和清单中 27 个文件的内容、目标路径、大小及权限。官方二进制在运行时从 JayJay 发布页下载，没有放入本仓库或我们的应用包。

- 识别 QNX 6.5 x86、root 权限、NBT 视频组件和原车 Apple 认证设备节点；这不等同于验证全部车型和固件兼容性。
- 安装前把现有两个插件目录的普通文件备份到当前电脑，包含已有配置、日志和配对数据；特殊文件、链接和超过 128 MB 的备份会被拒绝。
- 在独立目录写入、回读校验，然后替换运行目录，最后激活 HMI 插件目录。保留旧目录用于恢复。
- 保留 `iap.off`、已有解码选择、`vid.dpi`、网关地址和配对文件；首次安装解码器时默认打开硬件解码，安装时清除 `disabled`。
- 仅终止本项目相关服务，不终止原厂 HMI / `io-nme`。使用 ZGW / HSFZ 6801 的 ECU `0x63` 诊断复位，不调用 QNX 系统关机。
- 首次成功识别车机后记住 SSH 身份；身份变化时拒绝写入。更换车辆可以在高级选项清除身份。
- 密码只在内存中使用，每次操作后清空；不会写入日志或 Git。首次 SSH 连接使用首次信任，仍应确认自己连到正确车辆。

## 失败与恢复

普通传输失败不会替换原有插件。激活过程中的命令失败会尝试还原旧目录；连接中断、断电或回滚失败时无法保证自动恢复，程序会保留安装锁和本地备份并明确提示状态未知。

保持车辆供电，恢复 ENET / SSH 后，在**原安装电脑**打开高级选项，点“恢复上次安装前备份”。程序校验车机 SSH 身份和备份哈希，确认远端激活脚本未在运行，再暂存并恢复相应备份。恢复操作本身也会先备份当前状态。没有对应备份或身份不匹配时不会自动恢复。

备份仅覆盖上述插件目录的普通文件及权限，不是车机完整磁盘镜像，也不保留空目录。首次安装前没有插件时，恢复会把本次安装的两个目录移到事务目录。安装与恢复后的旧文件仍保留在车机事务目录中，不自动清理其他事务；空间不足时停止，需人工导出和核对旧事务后再整理。

点击“打开备份 / 日志”查看本机文件：

- macOS：`~/Library/Application Support/ID4CarPlayInstaller/`
- Windows：`%LOCALAPPDATA%\ID4CarPlayInstaller\`

备份可能包含手机配对密钥。不要公开上传整个备份目录。需要排查问题时先分享 `logs` 中的文字日志。

## 从源码运行与构建

需要带 Tk 的 Python 3.13。macOS / Windows 都可以运行：

```sh
python -m pip install -r vehicle_installer/requirements.txt
python -m vehicle_installer
```

构建独立应用，必须在目标操作系统执行：

```sh
python -m pip install -r vehicle_installer/requirements-build.txt
python -m unittest discover -s vehicle_installer/tests -v
python -m vehicle_installer.build
```

输出在 `dist/`。Windows 构建也可运行 GitHub Actions 的 [Build vehicle installer](https://github.com/ch549235962/ID4-Carplay-Optimized/actions/workflows/build-vehicle-installer.yml)，包含故障注入测试和打包后 GUI 自检。

```sh
python -m vehicle_installer --self-test --report selftest.json
```

该自检只创建隐藏 GUI、验证依赖和包内清单，不连接车辆。测试范围与尚未验证的部分见 [VALIDATION.md](VALIDATION.md)。
