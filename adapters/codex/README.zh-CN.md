# Context Guardian for Codex

[English](README.md) · 简体中文

Context Guardian 的 Codex Assisted Checkpoint 集成。

目前 Codex 没有本项目可以依赖的、受支持的 pre-compaction hook，因此这个适配器
不会宣称能够自动拦截原生 compaction，而是提供手动 `context-guardian` skill 和
可移植的 checkpoint 文件。

## 流程

```text
Codex 任务
  ↓
手动调用 Context Guardian skill
  ↓
收集当前消息
  ↓
Keep / Drop 审查
  ↓
.agents/context-guardian.md
  ↓
Codex 继续工作并读取 checkpoint
```

## 从当前仓库安装

先安装 Python Core，再按照当前 Codex CLI 支持的方式添加本地 marketplace/plugin。
本目录包含 plugin manifest 和 skill。对于本地项目，也可以将 skill 放到项目的
`.agents/skills/context-guardian/` 中。

skill 使用的命令是：

```bash
context-guardian checkpoint messages.json --output .agents/context-guardian.md
```

它与 Pi、DeepSeek Harness 原生适配器共享同一套 Inspector、Policy 和
ReviewDecision。未决候选会保守地保留。

发布后无需 clone 仓库即可安装 Python Core 和 Codex plugin：

```bash
python -m pip install context-guardian-core
codex plugin marketplace add deulofeu1/context-guardian
codex plugin add context-guardian-codex@context-guardian
```

## 交互式 fixture

在仓库根目录运行：

```bash
npm run codex-fixture-smoke
```

fixture 会注入共享 OAuth 场景，暂停等待真实 Keep/Drop 选择，并验证 checkpoint
包含目标、public API 约束、PostgreSQL 决定、SQLite 失败原因和 `auth.py` TODO，
同时排除命令输出。它验证手动 checkpoint 集成，不会伪造不存在的 Codex 原生 hook。
