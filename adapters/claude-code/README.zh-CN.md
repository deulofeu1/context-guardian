# Context Guardian for Claude Code

[English](README.md) · 简体中文

Context Guardian 的 Claude Code 适配器。它使用 Claude Code 官方的 `PreCompact`
hook，在 `/compact` 前读取 transcript、审查不确定候选，并写入一份简短的
preservation checkpoint。

## 当前实现方式

Claude Code 的 `PreCompact` 可以阻止 compaction，但这个 hook 合同没有提供把
`additionalContext` 直接注入同一次 compaction 请求的通道。因此手动压缩采用
安全的两步流程：

```text
/compact
  ↓
PreCompact hook
  ↓
Keep / Drop 审查
  ↓
写入 .claude/context-guardian.md
  ↓
阻止一次
  ↓
/compact Read .claude/context-guardian.md and preserve every reviewed item
  ↓
Claude Code 原生 compaction
```

自动 compaction 会写入 checkpoint，然后 fail-open 继续原生压缩，避免上下文已
经接近上限时阻塞 Agent。

## 从当前仓库安装

先安装 Python Core，再为 Claude Code 会话加载插件：

```bash
python3 -m pip install -e /absolute/path/to/ContextGuardian
claude --plugin-dir /absolute/path/to/ContextGuardian/adapters/claude-code
```

适配器使用本地规则 Inspector。Claude Code 不会把当前模型调用接口暴露给外部
command hook，因此不会额外索取 API Key，也不会把凭证传给 Python。规则模式不
需要模型即可运行。

checkpoint 默认写入 `.claude/context-guardian.md`，可用
`CONTEXT_GUARDIAN_CLAUDE_CHECKPOINT` 修改；自动化时可用
`CONTEXT_GUARDIAN_REVIEW_MODE=keep` 或 `drop`。

发布后无需 clone 仓库即可安装 Python Core 和 marketplace plugin：

```bash
python -m pip install context-guardian-core
claude plugin marketplace add deulofeu1/context-guardian
claude plugin install context-guardian-claude@context-guardian
```

## 交互式 fixture

从仓库根目录运行：

```bash
npm run claude-fixture-smoke
```

它会把预置的 Claude 风格 transcript 注入真实 `PreCompact` hook，在终端显示
Keep/Drop 选择，验证第一次调用会阻止 compaction 并写入 checkpoint，再验证带有
checkpoint 指令的第二次调用允许原生 compaction 继续。不需要先进行很长的真实
对话，也不需要 API Key。最终 Claude Code UI 验收时，再加载插件并在真实会话中
执行 `/compact`。

## 兼容性与失败行为

适配器针对当前 Claude Code `PreCompact` command hook 合同。如果 transcript、
Python Core、交互终端或 checkpoint 写入失败，适配器会把 warning 写到 stderr，
返回空的 allow 响应，让 Claude Code 原生 compaction 继续。
