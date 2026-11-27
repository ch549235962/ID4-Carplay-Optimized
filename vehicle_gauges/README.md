# NBT 仪表电脑端配置工具（开发版）

电脑负责 VIN 核对、ECU 身份识别和配置选择；未来 NBT 只保存选定的小配置。**当前完成的是电脑端身份读取及配置准备，不是可刷写的全车型温度表。当前实车验证配置数为 0，不生成可部署数据包，不写车辆。**

首个候选车型：用户提供的 **2014 F20 / N13**。这是人工提示，不能代替实际 ECU 识别；程序不声称能只凭 VIN 离线确定已安装的发动机。

## 使用

在 0.2.2 桌面安装器点“仪表配置（开发版）”，或用 `--gauges` 参数单独打开。

1. ENET 连接车辆，填写**车辆网关 IPv4**，不是车机 IP。工具不猜地址、不扫描网段。
2. ECU 地址默认候选值 `12`，需要对照车辆诊断记录核对；不自动遍历其他 ECU。
3. 可填预期 VIN，用于与 ECU 回读核对；不一致则停止匹配。
4. 点“通过 ENET 读取身份”。仅发送 `22 F190/F187/F188/F189`，读取 VIN、厂商零件号、软件号和软件版本。没有任意命令入口，不发送复位、刷写、安全访问、例程或会话切换。
5. 可导入本地身份 JSON，生成标有 `deployable=false` 的**待验证任务包**；它不是刷写文件。

原始报告保存在安装器数据目录 `gauges/identity-private.json`，含 VIN，仅保留本机。任务包使用 VIN SHA-256 绑定，没有 VIN 明文；哈希不是强匿名保证，也不能证明发动机型号。工具不调用联网 VIN 解码或上传报告。

命令行支持 macOS / Windows：

```sh
python -m vehicle_gauges identify --gateway YOUR_GATEWAY_IP --ecu 12 --output identity-private.json
python -m vehicle_gauges plan --report identity-private.json --vehicle "2014 F20 N13" --output needs-validation.json
python -m unittest vehicle_gauges.test_provision -v
```

## 匹配与后续实现

- 精确匹配 ECU 地址、零件号、软件号及软件版本；不只匹配 N13 或车型。身份缺失、VIN 冲突和多个匹配均拒绝。
- 编辑任务包的配置名称或 `deployable` 不能绕过程序内的已验证配置库。
- 水温、油温、增压分别验证，不能用水温代替油温。压力需区分绝对压力与相对增压，确认环境压力来源。
- 通用 `F4xx` 映射不保证 BMW ECU 支持；本工具不自动尝试未知实时地址。
- 配置库在电脑，未来车机只带选定信号。拟定策略：温度 1 Hz、压力最多 4 Hz、单个在途请求、页面关闭停采、过期清空、ECU 身份变化停采。
- 上述采集策略尚未在 QNX 实现或测量。下一阶段需要实际 N13 身份报告、经验证的数据标识／布局／换算及参考读数，才能实现并验证原始 x86 NBT 采集与仪表插件。当前不宣称覆盖所有 NBT 发动机，也没有实测负载降低幅度。

参考：[HSFZ／UDS 协议](https://github.com/HadiCherkaoui/klartext/blob/main/docs/protocol-reference.md)、[通用 PID 边界](https://github.com/HadiCherkaoui/klartext/blob/main/docs/standard-pids.md)、[ECU 数据库覆盖](https://github.com/gediz/bmw-unified-db)。本项目独立实现，没有复制这些项目的协议代码或 BMW 数据库。
