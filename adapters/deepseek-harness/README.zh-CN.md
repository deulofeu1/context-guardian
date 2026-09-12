# Context Guardian for DeepSeek Harness

[English](README.md) · 简体中文

这个适配器在 DeepSeek Harness 原生上下文压缩前增加人工审查：

```text
Harness 历史 → Context Guardian 检查 → Keep / Drop 审查 → Harness 原生摘要
```

它是 `dsh-compaction-basic` 的装饰器。DeepSeek Harness 继续负责压缩范围、
token 统计、会话事件、摘要格式、持久化和 `/compact` 命令。如果 Python、桥接、
模型抽取或人工审查不可用，适配器会记录 warning 并继续原生 compaction。

## 安装

DeepSeek Harness 目前仍是 developer preview，适配器锁定 `0.1.5-rc.x` API 系列。
适配器已经发布，安装 Python 核心并加入 Web profile：

```bash
python3 -m pip install context-guardian-core
dsh plugin --profile web add context-guardian-deepseek-harness
```

从源码试用时，可以把包名替换为：

```bash
dsh plugin --profile web add /absolute/path/to/ContextGuardian/adapters/deepseek-harness
```

由于 DeepSeek Harness Web 会在选中的 agent preset 内组合 compaction，仅安装包
还不够。请复制 `standard` preset，保持其他内容不变，把其中的
`compaction-basic` 行替换为 `context-guardian-deepseek-harness`，然后选择该
preset 或将它设为默认。compaction 分组应包含：

```yaml
- id: compaction
  name: cordis:group
  group: true
  isolate:
    compaction: true
    toolResultPruner: true
  config:
    - id: context-guardian-compaction
      name: context-guardian-deepseek-harness
    - id: command-compact
      name: '@deepseek-ai/dsh-command-compact'
    - id: tool-result-pruner
      name: '@deepseek-ai/dsh-compaction-tool-result-pruner'
```

这是必须步骤，因为 Harness 会在每个 session scope 内挂载 preset，profile 级别
的插件行不能覆盖 preset 自己的 `compaction-basic` 行。

Python 核心需要安装在 `dsh` 使用的环境中，也可以显式指定解释器：

```bash
python3 -m pip install -e /absolute/path/to/ContextGuardian
export CONTEXT_GUARDIAN_PYTHON=/absolute/path/to/python
```

适配器不会接收或转发 `DEEPSEEK_API_KEY`。结构化检查会通过 Harness 当前的
`ctx.llm` 路由执行，由 Harness 负责解析 Provider 凭证。

如果核心安装在虚拟环境中，启动 Harness 前设置
`CONTEXT_GUARDIAN_PYTHON=/absolute/path/to/venv/bin/python`。

在 Windows 上，bridge 会在保持最小子进程环境的同时传递 Python 网络栈所需的运行时变量。
如果 `python3` 解析到了 Microsoft Store 占位符，请在启动 Harness 的同一个 PowerShell
会话中显式指定解释器：

```powershell
$env:CONTEXT_GUARDIAN_PYTHON = (Get-Command python).Source
$env:CONTEXT_GUARDIAN_DEBUG = "1"
$env:CONTEXT_GUARDIAN_TIMEOUT_MS = "120000"
dsh --profile web
```

bridge 默认超时为 120 秒，也可以用 `CONTEXT_GUARDIAN_TIMEOUT_MS` 调低（上限为 120 秒）。
启用 debug 后，适配器会记录已加载，并报告检查候选和需要人工审查的候选数量。

## 交互式验证

启动 Web profile：

```bash
dsh --profile web
```

要验证完整流程而不进行很长的真实对话，在仓库根目录运行：

```bash
env PATH="/path/to/node-22.19/bin:$PATH" npm run dsh-fixture-smoke
```

fixture 会创建隔离的 Web profile，预置足够长的会话，打开 Harness UI，并在
SQLite 候选上暂停，让你选择 Keep 或 Drop，随后确认原生 `/compact` 成功。它
使用 replay model，不需要 DeepSeek API Key。结束临时 Web 进程时按 Ctrl-C。

在没有 answerer 的无头模式中，未决候选会保守地 Keep；也可以用
`CONTEXT_GUARDIAN_REVIEW_MODE=keep` 或 `drop` 绕过询问 UI。

## 禁用或卸载

临时禁用时，在 `Settings → Agent Presets` 中选择原生 `standard` preset，设为
默认并新建 session。自定义 preset 可以保留，之后还可重新启用。

要完全卸载，先切换离开自定义 preset，再移除 profile 插件；之后可以删除自定义
preset：

```bash
dsh plugin --profile web remove context-guardian-deepseek-harness
```

原生 `standard` preset 会恢复 Harness 原本的 compaction 流程。如果卸载命令
失败，先执行 `dsh plugin --profile web list` 检查当前 profile，不要直接修改整个
DSH 目录。

## 本地开发

```bash
npm install
npm --workspace adapters/deepseek-harness run typecheck
npm --workspace adapters/deepseek-harness run test
```

这个适配器与 Python distribution、Pi 适配器分别发布，因此每个宿主可以按自己
的生命周期和 UI 合同独立演进。
