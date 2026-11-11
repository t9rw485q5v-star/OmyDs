import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.toml"

def load_config():
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"找不到配置文件：{CONFIG_PATH}, 请从 config.example.toml 复制")

    with open(CONFIG_PATH, "rb") as f:
        cfg = tomllib.load(f)

    api = cfg["api"]
    # key 不能是示例占位符
    if api.get("key", "").startswith("sk-") and "keykeykey" in api["key"]:
        raise RuntimeError("检测到示例 key，请填入真实 DeepSeek API key")

    return cfg