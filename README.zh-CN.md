# Context Guardian

> 别让你的 coding agent 忘记错误的东西。

[English](README.md) · 简体中文

> 实验性 Alpha：Context Guardian 不保证一定改善上下文压缩、摘要质量或 Agent
> 表现。它是宿主原生 compaction 外的一层检查和人工审查能力，不是已经被证明有效的
> 上下文优化器。

Context Guardian 在 AI Agent 压缩上下文前增加一层人工审查。它不替代 Agent
自己的记忆系统、摘要器、token 管理器或原生 compaction 引擎，而是把隐藏的
Keep/Drop 决策变得可检查。

```text
上下文
  ↓
宿主原生 Preview
  ↓
语义审计
  ↓
自动修正 / 接受 Preview
  ↓
最多 3 个主题问题
  ↓
增量指导
  ↓
Agent 原生 Compaction
```

## 为什么需要它

Agent 经常会在压缩时丢掉“为什么某条路径被放弃”。之后它可能重复同一个
失败方案。Context Guardian 会在宿主 Agent 总结上下文前，找出长期有效的
目标、约束、决定、失败尝试和未完成工作，同时过滤临时噪声。人工判断面向主题，
不再面向孤立句子。

## 实验性质与项目边界

这是一个实验性 Alpha 项目。目前的实现是用于探索“人参与的上下文压缩控制”的
实践试验台，并不表示每次真实对话都能得到更好的摘要，也不保证一定改善 Agent
后续工作。审查策略可能出现误保留或误丢弃，最终效果还取决于宿主版本、模型、
对话内容、Provider 行为和用户选择。

你可以基于这个项目继续开发新的宿主适配器、审查策略和评估方法。请把输出看作
提供给宿主原生 compactor 的辅助指导，在重要会话中使用前保留回退路径，并用自己
真实的工作负载进行验证。

## 安装已发布的包

Python 核心和两个宿主适配器都已经发布。正常使用不需要克隆仓库，也不需要安装
仓库的 workspace 依赖；宿主 CLI 仍然需要单独安装。Python distribution 使用
`context-guardian-core`，安装后的 CLI 仍然叫 `context-guardian`。

Pi 安装核心和适配器：

```bash
python3 -m pip install context-guardian-core
pi install npm:@context-guardian/pi
```

需要 Pi `0.82.1` 和 Node.js `22.19.0+`。如果核心安装在虚拟环境中，启动 Pi
前显式指定解释器：

```bash
export CONTEXT_GUARDIAN_PYTHON=/absolute/path/to/venv/bin/python
```

DeepSeek Harness 安装核心，并把适配器安装到 Web profile：

```bash
python3 -m pip install context-guardian-core
dsh plugin --profile web add context-guardian-deepseek-harness
```

需要 DeepSeek Harness `0.1.5-rc.x` 和 Node.js `22.19.0+`。Harness Web 还需要
额外进行一次 preset 设置，见下面的适配器说明。

npm 包采用 GitHub Actions Trusted Publishing（OIDC）发布，不使用长期
`NPM_TOKEN`。每个 npm 包的 Trusted Publisher 配置方法见
[`docs/publishing.md`](docs/publishing.md)。

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
context-guardian inspect examples/conversation.json --preview-file native-preview.txt --json
context-guardian review examples/conversation.json --preview-file native-preview.txt
context-guardian verify examples/conversation.json
```

`verify` 是确定性的发布前 smoke test，会检查原生 Preview 审计修正、噪声移除、
ID 稳定性、问题数量上限和 Guidance 输出。它很快，但不能代替 Pi/DSH 的交互式
fixture 测试。

### Pi

从源码运行完整交互式 fixture：

```bash
npm run pi-fixture-smoke
```

它会创建一段预置的长对话，打开 Pi UI，并让你手动选择不确定候选的 Keep/Drop，
所以不需要先进行很长的真实对话。适配器先调用 Pi 原生 compaction 生成未提交的
Preview，再用当前模型审计；只有需要修正或确认保留主题时才第二次调用原生
compaction。Python 子进程不会收到 API Key。Node.js 需要 `22.19.0+`，Pi 兼容范围
是 `0.82.1`。

若要在已有 Pi 会话中直接加载仓库中的扩展，请看
[`adapters/pi/README.md`](adapters/pi/README.md)。

### DeepSeek Harness

安装包后，按适配器文档创建基于 `standard` 的用户 preset，并将其中的原生
`compaction-basic` 替换为 Context Guardian。运行交互式 fixture：

```bash
env PATH="/path/to/node-22.19/bin:$PATH" npm run dsh-fixture-smoke
```

fixture 会预置一段足够长的会话，打开 Harness Web UI，在 SQLite 失败方案上
暂停询问 Keep/Drop，并验证目标、约束、PostgreSQL 决定、`auth.py` TODO 及有价值
的失败背景进入原生 compaction Guidance。它使用 replay model，不需要 DeepSeek
API Key。详细步骤见
[`adapters/deepseek-harness/README.md`](adapters/deepseek-harness/README.md)。

## 工作模式

- 规则模式：本地、确定性、保守，是 CLI 默认模式。
- Native 适配器：先得到宿主 Preview，再进行语义审计；必要时把增量修正交给
  宿主原生 compaction 第二次调用。
- 默认最多询问 3 个主题问题，可用 `CONTEXT_GUARDIAN_MAX_REVIEW_QUESTIONS=0..3`
  调低；设为 0 表示不弹窗并采用保守处理。
- OpenAI 模式：独立 CLI 的可选 Provider，需要时安装 `context-guardian-core[openai]` 并配置 Key。

如果桥接、模型调用或审查 UI 失败，适配器会 fail-open，继续宿主的原生
compaction。

## 禁用或卸载

两个适配器都是可选的，不会锁定项目或会话，也不会修改项目源文件。

Pi 如果之前只是用 `pi -e` 临时加载扩展，之后不再带这个参数即可。若是通过
包安装，则执行：

```bash
pi remove npm:@context-guardian/pi
# 如果是项目级安装：
pi remove npm:@context-guardian/pi -l
```

`pi uninstall` 是 `pi remove` 的别名。移除包不会删除 Pi 会话数据，之后的
`/compact` 会回到 Pi 原生流程。

DeepSeek Harness 临时禁用时，先在 `Settings → Agent Presets` 选择原生
`standard` preset，设为默认并新建 session。要完全移除 Web profile 中的适配器：

```bash
dsh plugin --profile web remove context-guardian-deepseek-harness
```

之后可以删除自定义的 `context-guardian` preset。由于 DSH 的 profile bundle 和
preset 是两层配置，必须先切回 `standard`，再删除 bundle。如果卸载命令失败，
先执行 `dsh plugin --profile web list` 检查当前 profile，不要直接删除整个 DSH
目录。

Claude Code 和 Codex 不属于当前 `main` 发布版本。之前的实验性适配器仍保留在
`exploration/claude-code-codex` 分支。如果你曾经在本机安装过实验性的 Claude Code
`PreCompact` hook，只需从 Claude Code 设置中删除这一条 hook；否则不需要恢复 CC。

## 集成能力矩阵

| 平台 | 级别 | 自动触发 | 宿主模型 | 人工审查 | 保留方式 |
| --- | --- | --- | --- | --- | --- |
| Pi | Native | 是 | Pi 当前模型 | Pi UI，最多 3 个主题 | Preview 审计 + native `customInstructions` 重试 |
| DeepSeek Harness | Native | 是 | Harness 当前 `ctx.llm` 路由 | `userQuestions`，最多 3 个主题 | Preview 审计 + native 输入重试 |

当前版本聚焦于原生 compaction 集成。统一接口和能力声明见
[`docs/adapter-contract.md`](docs/adapter-contract.md) 与
[`adapters/capabilities.json`](adapters/capabilities.json)。

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
`dsh-fixture-smoke` 是验证 Preview、审计、主题选择和最终原生 compaction 的重点测试。

## 项目边界

Context Guardian 不实现新的 Agent loop、上下文窗口管理、会话数据库、向量库、
RAG 或独立摘要器。宿主已经提供的能力由对应适配器复用。

## 许可证

MIT。
