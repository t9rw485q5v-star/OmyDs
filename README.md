# OmyDs (O my DeepSeek)

> 一个跑在终端里的 DeepSeek AI 助手。没有客户端，没有侧边栏，只有你的 shell 和一个能帮你读写文件的家伙。

当前版本：**v0.1.7**

---

## 目录

- [为什么是终端](#为什么是终端)
- [核心特性](#核心特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [配置](#配置)
- [使用](#使用)
- [安全与隐私](#安全与隐私)
- [数据存储](#数据存储)
- [项目结构](#项目结构)
- [License](#license)

---

## 为什么是终端

因为它不打扰你。没有红点、没有弹窗、没有"在吗"。你想聊天的时候敲一句 `OmyDs`，不想聊的时候它就是一串躺在 `$PATH` 里的字符——不会主动来找你。

## 核心特性

- **多会话管理** — 新建、加载多个历史对话，退出时自动保存，下次接着聊。
- **原生的工具调用（Function Calling）** — AI 拥有自己的“手脚”。它能自主决定何时调用 `read_file` 读取本地代码，或调用 `write_file` 修改文档，不需要你死记硬背特殊指令。
- **企业级安全沙箱** — AI 默认只能在当前项目目录下活动。如果要读写外部文件，会触发终端的提权确认 `[y/N]`。敏感文件（如 `config.toml`、`~/.ssh`）被底层强制物理隔离。
- **AI 自动记忆** — 由模型自行判断哪些信息值得长期记住，提炼后写入 `~/.omyds/memory.md`，跨会话生效。
- **指令热更新** — 旧会话无需删除。每次请求都会自动注入你最新修改的 `agent.md` 和最新的工具集。
- **终端高级编辑** — `prompt_toolkit` 驱动，支持左右移动光标、上下翻阅历史、全链路防中文吞字。
- **极简加载动画** — API 思考时自带终端 Spinner，不再干瞪眼。

## 环境要求

- Python 3.11+（依赖内置的 `tomllib`）
- [uv](https://github.com/astral-sh/uv)（推荐使用，极速包管理）
- 一个可用的 DeepSeek API Key

## 安装

推荐使用 `uv` 进行安装和管理，它会自动帮你处理虚拟环境和依赖隔离：

```bash
git clone <你的仓库地址>
cd OmyDs

# 同步依赖并创建虚拟环境
uv sync

# 将 OmyDs 注册为全局命令
uv pip install -e .
```

*(注：如果你坚持使用传统的 pip，也可以执行 `python -m venv .venv && source .venv/bin/activate && pip install -e .`)*

## 配置

首次运行前，需要在项目根目录创建以下配置文件。它们都已被 `.gitignore` 忽略，请放心填入私人信息。

### 1. `config.toml` — API 与模型

```toml
[api]
key = "sk-在此填入你的真实 API Key"
base_url = "https://api.deepseek.com"
model = "deepseek-chat"

[chat]
# 仅在 agent.md 不存在时作为兜底系统提示词
system_prompt = "你是 OmyDs，一个简洁、直接的终端聊天助手。"
```

### 2. `agent.md` — 人设与规则

新建 `agent.md` 定义 OmyDs 的性格和行为约束。你可以复制 `agent.example.md` 作为起步模板，并随意修改。

> **优先级**：`agent.md` > `config.toml` 里的 `chat.system_prompt`。

### 3. `greet.toml` — 启动共识

控制终端启动时的 Logo 和“三点共识”提示。如果觉得啰嗦，随时把 `remind` 关掉。

```toml
[greeting]
remind = true
message = """
在开始之前，请记住这三点共识：
1. 尊重他人的隐私。
2. 输入之前先思考。
3. 能力越大，责任越大。
"""
```

## 使用

启动后，直接使用自然语言与它交流。它会在需要时自动调用工具。

```bash
uv run OmyDs
```

| 操作 | 说明 |
| --- | --- |
| `exit` / `quit` | 退出程序（会提示保存当前对话） |
| `Ctrl + C` | 强制打断当前对话或退出 |
| 「帮我看看 omyds/config.py」 | AI 会调用 `read_file` 工具读取文件并分析 |
| 「在 README.md 末尾加一句话」 | AI 会调用 `write_file` 工具并让你确认写入 |
| `/history` | 打印当前会话的所有历史对话 |
| `/help` | 查看帮助指令 |

## 安全与隐私

OmyDs 拥有修改本地文件的能力，因此安全机制是内置且严格的：

1. **沙箱锁定**：默认只允许操作当前工作目录。
2. **防路径穿越**：任何包含 `../` 尝试逃逸的路径会被直接拦截。
3. **提权确认**：越界操作或修改文件前，必须经过你在终端手动输入 `y` 确认。
4. **静默脱敏**：系统权限报错会被重写，防止恶意 AI 通过报错盲注探测你的系统结构。

## 数据存储

所有用户数据都在家目录下的 `~/.omyds/`，与项目仓库完全隔离：

| 数据类型 | 路径 |
| --- | --- |
| 会话历史 | `~/.omyds/sessions/*.json` |
| 长期记忆 | `~/.omyds/memory.md` |
| 输入历史 | `~/.omyds_history` |

想「格式化」OmyDs 的记忆，删掉 `memory.md` 即可；想彻底重来，删整个 `~/.omyds/`。

## 项目结构

```text
OmyDs/
├── omyds/               # 核心源码
│   ├── __main__.py      # 主控制循环与 Agent 逻辑
│   ├── config.py        # 配置解析与防御降级
│   ├── security.py      # 沙箱与路径校验
│   ├── storage.py       # 记忆与多会话持久化
│   ├── logo.py          # ASCII Art 门面
│   └── tools/           # 插件与工具注册中心
│       ├── read_file.py
│       └── write_file.py
├── agent.example.md     # 人设模板
├── config.example.toml  # 配置模板
├── greet.toml           # 启动共识配置
├── pyproject.toml       # uv/打包配置
└── uv.lock              # 锁定的依赖版本
```

## License

MIT

---

*O my DeepSeek. 它不打扰你，但它记得你。*