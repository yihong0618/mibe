# mibe

监听 Codex 会话日志，通过小爱音箱播报任务状态。

## Notes

1. 目前只支持 codex (Claude vibe PR welcome)
2. 目前的语音播报是固定的，你可以自己改

## 快速开始

参考项目 [MiService](https://github.com/yihong0618/MiService)

```bash
# 安装依赖
uv venv
uv sync 

# 设置环境变量
export MI_USER="小米账号"
export MI_PASS="小米密码"
export MI_DID="设备miotDID"  # 可选，不设则用第一个设备


# 验证登录 & 查看设备
uv run python mibe.py login

# 开始监听
uv run python mibe.py monitor
```

## 子命令

| 命令 | 说明 |
|------|------|
| `login` | 测试登录，列出可用设备 |
| `monitor` | 监听 Codex 日志并播报 |

`monitor` 可选参数：

- `--replay-existing {none,latest,all}` — 启动时回放已有日志（默认 `none`）
- `--verbose` — 详细日志

## 行为

| 事件 | 播报 | 动作 |
|------|------|------|
| `task_started` | vibe启动 | 播完后静音，定时发送静默 TTS 保持亮灯 |
| `task_complete` | 任务完成 | 恢复音量后播报 |
| `turn_aborted` | 任务中断 | 恢复音量后播报 |

退出时（Ctrl+C / SIGTERM）自动恢复音量。

## 感谢

- yetone
