from pathlib import Path

ALLOWED_ROOT = Path.cwd()

FORBIDDEN_NAMES = {
    "config.toml", ".env", "id_rsa", "id_ed25519", 
    ".git", ".venv", "agent.md", "__pycache__"
}

def validate_path(user_path: str) -> Path:
    """校验用户提供的路径，越界时触发提权询问。"""
    
    # 支持绝对路径和相对路径
    path_obj = Path(user_path).expanduser()
    if not path_obj.is_absolute():
        resolved = (ALLOWED_ROOT / path_obj).resolve()
    else:
        resolved = path_obj.resolve()

    # 1. 拦截绝对黑名单
    for part in resolved.parts:
        if part in FORBIDDEN_NAMES:
            raise PermissionError(f"安全系统拦截：禁止读取敏感文件 '{part}'")
    if resolved.suffix in [".key", ".pem"]:
        raise PermissionError(f"安全系统拦截：禁止读取后缀为 {resolved.suffix} 的密钥文件")

    # 2. 检查是否在沙箱内
    try:
        resolved.relative_to(ALLOWED_ROOT.resolve())
    except ValueError:
        # 越界了！触发提权询问
        print(f"\n\033[33m[安全警告] 尝试读取沙箱外部的文件：\n{resolved}\033[0m")
        ans = input("\033[33m是否允许本次读取？[y/N] \033[0m").strip().lower()
        if ans != 'y':
            raise PermissionError("用户拒绝了提权访问")
        # 如果输入了 y，就放行

    return resolved