# gripper_hl

慧灵 **Z-EFG-C65** 单测上位机（作用类似 `sensors-arm` / `gello`）：Web 控制台驱动 hik-sensors `kind=gripper_huiling`。

协议与桌面 `慧灵C65/huiling_clean` 一致（Modbus RTU）；驱动实现见 `sensors/src/sensors/drivers/gripper/huiling_zefg_c65.py`。

## 布局

```text
gripper_hl/
  configs/
    default.yaml            # host：端口、sensor_id、dry_run
    sensors_gripper.yaml    # hik-sensors 设备清单
  sensors -> ../sensors     # 软链/junction（与 gello 相同）
  src/gripper_hl_app/
```

Windows 建 junction（管理员或开发者模式）：

```bat
cd gripper_hl
mklink /J sensors ..\sensors
```

## 安装

```bash
cd autodl-tmp
# 已有工作区 venv：
.venv\Scripts\pip install -e ./gripper_hl[hardware]
# 或: pip install -e ./sensors && pip install -e ./gripper_hl[hardware]
```

## 启动

```bash
cd gripper_hl
gripper-hl web -c configs/default.yaml
# 真机：YAML dry_run: false，endpoint 设为 COM 口，或:
# gripper-hl web -c configs/default.yaml --no-dry-run
```

浏览器：http://127.0.0.1:7021/

## 功能

| 操作 | 说明 |
|------|------|
| 连接 / 断开 | 打开 Modbus 串口并采样状态 |
| 初始化 | 找零（`init_code==5` 完成）；行程内勿放物体 |
| 位置 / 速度 / 电流 | mm、mm/s、A；开=65、合=0 |
| Probe / 测速 / 串口列表 | 健康检查与吞吐 |

## API 摘要

| 路径 | 说明 |
|------|------|
| `GET /api/status` | 连接态 + 最新反馈 |
| `POST /api/connect` | `{ dry_run? }` |
| `POST /api/disconnect` | |
| `POST /api/initialize` | 找零 |
| `POST /api/command` | `{ position_mm?, position_norm?, open?, close?, speed_mm_s?, current_a? }` |
| `GET /api/ports` | 串口列表 |
| `GET /data` | SSE 状态流 |

## 依赖

- Python ≥ 3.10、工作区 `sensors`（含 `gripper_huiling`）
- 真机：`pyserial`、RS485 115200 8N1、从站 ID 1
