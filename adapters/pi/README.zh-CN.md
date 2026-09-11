# `@context-guardian/pi`

[English](README.md) · 简体中文

Context Guardian 的 Pi 适配器，在 Pi 原生上下文压缩前增加候选记忆审查。

## 安装

目前 Python 和 npm 包还没有发布。使用当前仓库时，先安装 Python 核心和
JavaScript 依赖：

```bash
python -m pip install -e /absolute/path/to/ContextGuardian
cd /absolute/path/to/ContextGuardian
npm install
```

正式发布后，面向最终用户的目标命令是：

```bash
pip install context-guardian
pi install npm:@context-guardian/pi
```

在包发布前，可以直接加载仓库中的扩展：

```bash
pi -e /absolute/path/to/ContextGuardian/adapters/pi/extensions/context-guardian.ts
```

或者从仓库根目录运行完整交互式验证：

```bash
npm run pi-fixture-smoke
```

适配器复用 Pi 当前模型和认证信息，不会把 Provider 凭证传给 Python 进程。
如果桥接或审查流程失败，会 fail-open，继续 Pi 原生 compaction。

兼容范围：Pi `0.82.1`，Node.js `22.19.0+`。

## 验证

快速无模型 smoke test：

```bash
npm install
npm run pi-smoke
```

完整 fixture 会创建一段预置的长对话，打开 Pi UI，并让你手动选择不确定候选
的 Keep/Drop；不需要先进行很长的真实对话。Pi 需要已经登录，因为适配器会
复用当前宿主模型。

## 本地开发

```bash
npm run typecheck
npm run pi-fixture-smoke
```
