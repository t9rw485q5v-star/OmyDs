# OmyDs (Oh my DeepSeek)

一个跑在终端里的 DeepSeek 聊天助手。名字来自一句感叹：Oh my DeepSeek。

目标很简单：在终端里有一个**自己完全掌控、知道每一行在干什么**的对话工具。
不追求功能大而全，追求**最小闭环先跑起来，然后按需长**。

## 特性（当前）

- 终端交互式多轮对话
- 流式输出，回复逐字打印
- 配置文件与代码分离（`~/.config/omyds/config.toml`）
- 内置斜杠命令：`/clear` 清空历史，`/exit` 退出
- 请求失败时自动回滚本轮用户消息，不在历史里留下半截对话

## 快速开始

### 1. 准备环境

需要 Python 3.11+（用到标准库 `tomllib`）。

```bash
git clone <你的仓库地址> OmyDs
cd OmyDs
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
