import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.toml"
CONFIG_EXAMPLE_PATH = Path(__file__).parent.parent /"config.example.toml"
AGENT_PATH = Path(__file__).parent.parent /"agent.md"
AGENT_EXAMPLE_PATH = Path(__file__).parent.parent /"agent.example.md"
GREET_PATH = Path(__file__).parent.parent / "greet.toml"

def load_config():
    # 1. 读 config.toml，如果不存在则读 example
    path_to_load = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_EXAMPLE_PATH
    if not path_to_load.exists():
        raise RuntimeError(f"找不到配置文件：{CONFIG_PATH} 或 {CONFIG_EXAMPLE_PATH}")
    
    if path_to_load == CONFIG_EXAMPLE_PATH:
        print(" \033[33m[警告：未找到 config.toml，正在使用 config.example.toml 的默认配置。请复制一份并填入你的 API Key]\033[0m")
        # 如果用 example，大概率没填 key
        # 这里为了防御，允许run，但肯定连不上，直到你建了 config.toml

    with open(path_to_load, "rb") as f:
        cfg = tomllib.load(f)

    api = cfg["api"]
    # key 不能是示例占位符
    if api.get("key", "").startswith("sk-") and "keykeykey" in api["key"]:
        raise RuntimeError("检测到示例 key，请填入真实 DeepSeek API key")

    return cfg

def get_system_prompt(cfg):
    """获取人设提示词：优先读 agent.md，否则读 agent.example.md，最后回退到 config.toml"""
    if AGENT_PATH.exists():
        with open(AGENT_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    elif AGENT_EXAMPLE_PATH.exists():
        with open(AGENT_EXAMPLE_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    else:
        # 如果 example 不存在，回退到 config.toml
        return cfg.get("chat", {}).get("system_prompt", "你是 OmyDs，一个简洁的终端助手。")

    GREET_PATH = Path(__file__).parent.parent / "greet.toml"

def get_greeting() -> str:
    """读取并组装启动时的训诫（如果没有开启则返回空字符串）"""
    remind_text = ""

    if GREET_PATH.exists():
        with open(GREET_PATH, "rb") as f:
            cfg = tomllib.load(f)
            greet = cfg.get("greeting", {})
            
            if greet.get("remind", True):
                # 如果 remind 是 true，返回自定义的训诫内容
                msg = greet.get("message", "").strip()
                if msg:
                    remind_text = f"\n{msg}\n"

    return remind_text