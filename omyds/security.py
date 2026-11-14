from pathlib import Path

ALLOWED_ROOT = Path.cwd()
FORBIDDEN_NAMES = {"config.toml", ".env", "id_rsa", "id_ed25519", ".git", ".venv", "agent.md", "__pycache__"}

# 自定义一个越界异常
class OutOfSandboxError(PermissionError):
    pass

def validate_path(user_path: str) -> Path:
    path_obj = Path(user_path).expanduser()
    if not path_obj.is_absolute():
        resolved = (ALLOWED_ROOT / path_obj).resolve()
    else:
        resolved = path_obj.resolve()

    for part in resolved.parts:
        if part in FORBIDDEN_NAMES:
            raise PermissionError(f"安全系统拦截：禁止读取敏感文件 '{part}'")
    if resolved.suffix in [".key", ".pem"]:
        raise PermissionError(f"安全系统拦截：禁止读取后缀为 {resolved.suffix} 的密钥文件")

    try:
        resolved.relative_to(ALLOWED_ROOT.resolve())
    except ValueError:
        # 触发自定义越界异常
        raise OutOfSandboxError(f"文件在沙箱外部: {resolved}")

    return resolved