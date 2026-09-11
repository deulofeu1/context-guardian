# Context Guardian

> 别让你的 coding agent 忘记错误的东西。

[English](README.md) · 简体中文

Context Guardian 在 AI Agent 压缩上下文前增加一层人工审查。它不替代 Agent
自己的记忆系统、摘要器、token 管理器或原生 compaction 引擎，而是把隐藏的
Keep/Drop 决策变得可检查。

```text
上下文
  ↓
检查
  ↓
自动保留 / 自动丢弃
  ↓
人工审查
  ↓
压缩指导
  ↓
Agent 原生 Compaction
```

## 为什么需要它

Agent 经常会在压缩时丢掉“为什么某条路径被放弃”。之后它可能重复同一个
失败方案。Context Guardian 会在宿主 Agent 总结上下文前，找出长期有效的
目标、约束、决定、失败尝试和未完成工作，同时过滤临时噪声。

## 安装状态

目前仓库可以从源码安装，但 Python 和 npm 包还没有发布。因此现在的流程是：
克隆或下载仓库 → 安装 Python 和 JavaScript 依赖 → 从仓库运行适配器。

发布后的无源码安装方式如下。这是目标中的最终用户体验，目前还不能作为安装
测试使用。宿主 CLI 仍然需要单独安装。另请注意，PyPI 上的 `context-guardian`
名称目前已被无关项目占用，发布前必须解决这个包名问题。

## 现在从源码使用

```bash
git clone https://github.com/deulofeu1/context-guardian.git
cd context-guardian

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
npm install
```

这里的 workspace 安装不会替你安装宿主 CLI。Pi 流程需要 Pi `0.82.1` 和 Node.js
`22.19.0+`；DeepSeek Harness 流程需要 `0.1.5-rc.x` API 系列和同样的 Node.js
运行时。

规则模式不需要 API Key：

```bash
context-guardian inspect examples/conversation.json
context-guardian inspect examples/conversation.json --json
context-guardian review examples/conversation.json
context-guardian verify examples/conversation.json
```

`verify` 是确定性的发布前 smoke test，会检查关键记忆保留、噪声移除、候选
ID 稳定性和 Guidance 输出。它很快，但不能代替真实的交互式 Pi 测试。

### Pi

从源码运行完整交互式 fixture：

```bash
npm run pi-fixture-smoke
```

它会创建一段预置的长对话，打开 Pi UI，并让你手动选择不确定候选的 Keep/Drop，
所以不需要先进行很长的真实对话。适配器复用 Pi 当前模型和认证信息，Python
子进程不会收到 API Key。Node.js 需要 `22.19.0+`，Pi 兼容范围是 `0.82.1`。

若要在已有 Pi 会话中直接加载仓库中的扩展，请看
[`adapters/pi/README.md`](adapters/pi/README.md)。

### DeepSeek Harness

先把本地适配器安装到 Web profile：

```bash
dsh plugin --profile web add "$PWD/adapters/deepseek-harness"
```

然后按适配器文档创建基于 `standard` 的用户 preset，并将其中的原生
`compaction-basic` 替换为 Context Guardian。运行交互式 fixture：

```bash
env PATH="/path/to/node-22.19/bin:$PATH" npm run dsh-fixture-smoke
```

fixture 会预置一段足够长的会话，打开 Harness Web UI，在 SQLite 失败方案上
暂停询问 Keep/Drop，并验证目标、约束、PostgreSQL 决定、`auth.py` TODO 及有价值
的失败背景进入原生 compaction Guidance。它使用 replay model，不需要 DeepSeek
API Key。详细步骤见
[`adapters/deepseek-harness/README.md`](adapters/deepseek-harness/README.md)。

## 发布后的无源码安装（目标）

```bash
python -m pip install context-guardian
pi install npm:@context-guardian/pi
dsh plugin --profile web add context-guardian-deepseek-harness
```

这些命令要等包正式发布且 Python 包名问题解决后才会生效。

## 工作模式

- 规则模式：本地、确定性、保守，是 CLI 默认模式。
- Pi 模式：让 Pi 当前模型输出结构化候选，再调用 Pi 原生 compaction。
- OpenAI 模式：独立 CLI 的可选 Provider，需要显式安装 `.[openai]` 并配置 Key。

如果桥接、模型调用或审查 UI 失败，适配器会 fail-open，继续宿主的原生
compaction。

## 开发与验证

```bash
pytest
ruff check .
npm install
npm run typecheck
npm run typecheck:dsh
npm run test:dsh
npm run pi-smoke
npm run pi-fixture-smoke
npm run dsh-fixture-smoke
```

其中 `pi-smoke` 是适合 CI 的快速无模型检查；`pi-fixture-smoke` 和
`dsh-fixture-smoke` 是验证完整人工选择流程的重点测试。

## 项目边界

Context Guardian 不实现新的 Agent loop、上下文窗口管理、会话数据库、向量库、
RAG 或独立摘要器。宿主已经提供的能力由对应适配器复用。

## 许可证

MIT。
