from pathlib import Path
import sys

BASE_DIR = Path(__file__).parent.parent
SANDBOX_ROOT = BASE_DIR / "sandbox"
SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)

ALLOWED_ROOT = SANDBOX_ROOT

FORBIDDEN_NAMES = {"config.toml", ".env", "id_rsa", "id_ed25519", ".git", ".venv", "agent.md", "__pycache__"}

class OutOfSandboxError(PermissionError):
    pass

def validate_path(user_path: str) -> Path:
    # ... (保持你之前的逻辑不变) ...
    path_obj = Path(user_path).expanduser()
    if not path_obj.is_absolute():
        resolved = (ALLOWED_ROOT / path_obj).resolve()
    else:
        resolved = path_obj.resolve()

    for part in resolved.parts:
        if part in FORBIDDEN_NAMES:
            raise PermissionError(f"安全拦截：禁止访问敏感文件 '{part}'")
    if resolved.suffix in [".key", ".pem"]:
        raise PermissionError(f"安全拦截：禁止读取密钥文件")

    try:
        resolved.relative_to(ALLOWED_ROOT)
    except ValueError:
        raise OutOfSandboxError(f"越界拦截：AI 被锁定在 {ALLOWED_ROOT.name} 目录内，无法访问外部文件。")

    return resolved

def set_workdir(new_dir: str):
    global ALLOWED_ROOT
    target = (BASE_DIR / new_dir).resolve() if not Path(new_dir).is_absolute() else Path(new_dir).resolve()
    if target == Path("/") or str(target).startswith("/etc"):
        raise PermissionError("拒绝挂载系统根目录或敏感目录！")
    ALLOWED_ROOT = target
    return str(target)

# 新增：恢复默认
def reset_workdir():
    global ALLOWED_ROOT
    ALLOWED_ROOT = SANDBOX_ROOT
    return str(ALLOWED_ROOT)