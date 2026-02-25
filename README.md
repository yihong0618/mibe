# mibe

[![CI](https://github.com/yihong0618/mibe/actions/workflows/ci.yml/badge.svg)](https://github.com/yihong0618/mibe/actions/workflows/ci.yml)

监听 Codex / Kimi 会话日志，通过小爱音箱播报任务状态。

## Notes

语音播报内容可以通过配置文件自定义

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
| `monitor` | 监听 Codex/Kimi 日志并播报 |

`monitor` 可选参数：

- `--replay-existing {none,latest,all}` — 启动时回放已有日志（默认 `none`）
- `--verbose` — 详细日志
- `--codex-only` — 仅监听 Codex 会话
- `--kimi-only` — 仅监听 Kimi 会话
- `-c, --config PATH` — 指定配置文件路径

## 行为

| 事件 | 播报 | 动作 |
|------|------|------|
| Codex `task_started` | codex启动 | 播完后静音，定时发送静默 TTS 保持亮灯 |
| Codex `task_complete` | codex完成 | 恢复音量后播报 |
| Codex `turn_aborted` | codex中断 | 恢复音量后播报 |
| Codex `request_user_input`（function_call） | codex需要你确认 + 问题内容 | 停止 keepalive，恢复音量后播报，保持未静音等待用户回复 |
| Codex `function_call`（新格式提权确认：`sandbox_permissions=require_escalated`） | codex需要你确认 + 授权说明/命令摘要 | 停止 keepalive，恢复音量后播报，保持未静音等待用户回复 |
| Kimi `TurnBegin` | kimi启动 | 播完后静音，定时发送静默 TTS 保持亮灯 |
| Kimi `TurnEnd` | kimi完成 | 恢复音量后播报 |

退出时（Ctrl+C / SIGTERM）自动恢复音量。
当 Codex 通过 `request_user_input` 向你提问，或通过 `exec_command` 请求提权确认时，会播报确认摘要。
多问题场景只播报“问题数量 + 第一个问题”。

## 配置文件

支持通过 TOML 配置文件自定义播报消息和设置。

配置文件搜索路径（按优先级）：
1. `-c, --config` 指定的路径
2. `./config.toml`
3. `~/.config/mibe/config.toml`

### 示例配置

```toml
[messages]
# Codex 相关消息
codex_started = "codex启动"
codex_complete = "codex完成"
codex_aborted = "codex中断"
codex_input_required = "codex需要你确认"
# 模板变量：{alert_text}、{first_question}
codex_input_single_template = "{alert_text}。{first_question}"
# 模板变量：{alert_text}、{question_count}、{first_question}
codex_input_multi_template = "{alert_text}，共有{question_count}个问题。第一个问题：{first_question}"
codex_input_fallback_question = "请查看终端中的问题"

# Kimi 相关消息
kimi_started = "kimi启动"
kimi_complete = "kimi完成"

[settings]
# Kimi 完成检测的静音时间（秒）
kimi_completion_silence = 2.0
# 提问提醒里朗读的第一个问题最大词数（中英文兼容计数：英文词块 + 汉字，避免 TTS 过长）
codex_input_question_max_words = 160
```

### Codex 提问提醒文案模板

当监听到 Codex 需要用户确认的 function call 事件时，mibe 会播报提醒。

- 触发条件：
  - `response_item -> function_call(name="request_user_input")`
  - `response_item -> function_call(*)` 且 `arguments.sandbox_permissions == "require_escalated"`（新格式提权确认）
- 模板变量：`{alert_text}`（提醒短语）、`{question_count}`（问题数量）、`{first_question}`（第一个问题内容）
- 多问题策略：`request_user_input` 只播报“数量 + 第一个问题”
- 提权确认策略（新格式）：优先播报 `justification`，否则播报命令摘要 `cmd`
- 长问题会按 `codex_input_question_max_words`（中英文兼容计数：英文词块 + 汉字）截断，并追加“后续请看终端”

复制 `config.toml.example` 作为起点：

```bash
cp config.toml.example config.toml
# 编辑 config.toml 自定义你的播报消息
```

## 感谢

- yetone
