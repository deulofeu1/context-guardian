# `@context-guardian/pi`

[English](README.md) · 简体中文

Context Guardian 的 Pi 适配器，在 Pi 原生上下文压缩前增加候选记忆审查。

## 安装

包已经发布。正常使用不需要克隆仓库，直接安装 Python 核心和 Pi 适配器：

```bash
python3 -m pip install context-guardian-core
pi install npm:@context-guardian/pi
```

需要 Pi `0.82.1` 和 Node.js `22.19.0+`。适配器在 macOS/Linux 上默认使用
`python3`，在 Windows 上默认使用 `python` 启动核心桥接。如果核心安装在虚拟环境中，
请指定绝对路径：

```bash
export CONTEXT_GUARDIAN_PYTHON=/absolute/path/to/venv/bin/python
```

桥接默认超时为 120 秒，可以通过 `CONTEXT_GUARDIAN_TIMEOUT_MS` 调低；超过 120 秒的值
会被限制为 120 秒。

如果要直接试用源码，可以使用 `pi -e` 或仓库中的交互式 fixture。`pi -e` 只对
当前运行有效，不需要卸载：

```bash
pi -e /absolute/path/to/ContextGuardian/adapters/pi/extensions/context-guardian.ts
```

或者从仓库根目录运行完整交互式验证：

```bash
npm run pi-fixture-smoke
```

适配器复用 Pi 当前模型和认证信息，不会把 Provider 凭证传给 Python 进程。
如果桥接或审查流程失败，会 fail-open，继续 Pi 原生 compaction。

## 禁用或卸载

如果之前使用 `-e` 临时加载扩展，之后不再带这个参数即可。通过包安装时执行：

```bash
pi remove npm:@context-guardian/pi
# 如果是项目级安装：
pi remove npm:@context-guardian/pi -l
```

`pi uninstall` 是别名。移除适配器不会删除项目文件或 Pi 会话，之后的
`/compact` 会继续使用 Pi 原生 compaction。

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
