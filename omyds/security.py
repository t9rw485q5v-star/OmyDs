from pathlib import Path

ALLOWED_ROOT = Path.cwd()

def validate_path(user_path: str) -> Path:
    """校验用户提供的路径是否在允许范围内。
    v0.1 仅做校验，不实际读取文件。
    """
    resolved = (ALLOWED_ROOT / user_path).resolve()
    try:
        resolved.relative_to(ALLOWED_ROOT.resolve())
    except ValueError:
        raise PermissionError(f"路径超出允许范围：{user_path}")
    return resolved