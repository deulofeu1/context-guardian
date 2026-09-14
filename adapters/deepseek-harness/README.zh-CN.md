# Context Guardian for DeepSeek Harness

[English](README.md) · 简体中文

这个适配器在 DeepSeek Harness 提交原生上下文压缩前审计 Preview：

```text
Harness 原生 Preview → Context Guardian 审计 → 自动修正 / 最多 3 个主题问题
→ 确定性 Reviewed Facts 区块 → Harness 原生 compaction 提交
```

它是 `dsh-compaction-basic` 的装饰器。DeepSeek Harness 继续负责压缩范围、
token 统计、会话事件、摘要格式、持久化和 `/compact` 命令。适配器只调用一次原生
`summarize()`，然后把一个确定性的 Reviewed Facts 内容区块追加到结果。如果 Python、桥接、
模型审计、UI 或事实生成不可用，适配器会记录 warning 并接受已经成功的 Preview；如果
Preview 本身失败才回到 Harness 原生 fallback。这是实验性能力，不保证一定改善
摘要或 Agent 表现。

可用 `CONTEXT_GUARDIAN_MAX_REVIEW_QUESTIONS=0..3` 设置问题硬上限；设为 0 表示
不弹窗，对未决主题采用保守处理。

## 安装

DeepSeek Harness 目前仍是 developer preview，适配器锁定 `0.1.5-rc.x` API 系列。
适配器已经发布，安装 Python 核心并加入 Web profile：

```bash
python3 -m pip install context-guardian-core
dsh plugin --profile web add context-guardian-deepseek-harness
```

适配器与 Python 核心共用带版本的 bridge 合同，必须保持在同一条 `0.3.x` 发布线上。
复现已发布配置时请固定两边的版本；例如 `0.3.1` 配对安装如下：

```bash
python3 -m pip install "context-guardian-core==0.3.1"
dsh plugin --profile web add context-guardian-deepseek-harness@0.3.1
```

如果旧核心不认识适配器使用的操作，适配器的 fail-open warning 会包含底层 bridge
错误，不再静默隐藏兼容性问题。

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

Provider 审计输出默认不可信。每个 finding 必须引用本次请求中的真实消息，证据片段还
必须能在对应原文中匹配，才能进入 Review 主题或 Reviewed Facts。宿主规划元数据、
system/plugin 消息、工具调用、路径、哈希、日志和已解决的机械错误不会进入人工审查。
这与 Pi 适配器使用同一套来源规则。

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
启用 debug 后，适配器会记录已加载，并只报告审计 finding 和主题问题数量，不输出
原始 prompt 内容。

## 交互式验证

启动 Web profile：

```bash
dsh --profile web
```

要验证完整流程而不进行很长的真实对话，在仓库根目录运行：

```bash
env PATH="/path/to/node-22.19/bin:$PATH" npm run dsh-fixture-smoke
```

fixture 会创建隔离的 Web profile，预置足够长的会话，并故意让 replay 的原生
Preview 缺少部分事实。打开 Harness UI 后，先选择名为
`Context Guardian 预置长对话（请先选择）` 的会话（或选择
`context-guardian-fixture-long` 工作区中的该会话），再输入 `/compact`。界面应
最多显示 3 个主题问题；请手动选择 Keep 或 Drop，然后确认原生 Preview 及其
确定性 Reviewed Facts 区块。它使用 replay model，不需要 DeepSeek API Key。结束临时 Web 进程时
按 Ctrl-C。

在没有 answerer 的无头模式中，高风险主题会保守地 Keep，低风险主题接受 Preview。

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
