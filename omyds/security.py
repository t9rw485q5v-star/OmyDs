from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SANDBOX_ROOT = BASE_DIR / "sandbox"
SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
ALLOWED_ROOT = SANDBOX_ROOT

FORBIDDEN_NAMES = {"config.toml", ".env", "id_rsa", "id_ed25519", ".git",
                   ".venv", "agent.md", "__pycache__"}
SYSTEM_ROOTS = tuple(Path(p) for p in
                     ("/etc", "/proc", "/sys", "/dev", "/boot", "/usr", "/bin",
                      "/sbin", "/lib", "/lib64", "/root"))


class OutOfSandboxError(PermissionError):
    pass


def resolve_path(user_path):
    if not isinstance(user_path, str) or not user_path.strip():
        raise ValueError("路径不能为空")
    path = Path(user_path).expanduser()
    return (path if path.is_absolute() else ALLOWED_ROOT / path).resolve()


def check_policy(path):
    for part in path.parts:
        if part in FORBIDDEN_NAMES:
            raise PermissionError(f"禁止访问敏感文件或目录：{part}")
    if path.suffix in {".key", ".pem"}:
        raise PermissionError("禁止访问密钥文件")
    if path == Path("/") or any(path.is_relative_to(p.resolve()) for p in SYSTEM_ROOTS):
        raise PermissionError("禁止访问系统目录")
    if path.is_relative_to(BASE_DIR) and not path.is_relative_to(SANDBOX_ROOT):
        raise PermissionError("禁止通过工具访问正在运行的 OmyDs 项目；请使用独立工作副本")


def validate_path(user_path, allow_outside=False):
    path = resolve_path(user_path)
    check_policy(path)
    if not allow_outside and not path.is_relative_to(ALLOWED_ROOT):
        raise OutOfSandboxError(f"目标 {path} 位于工作区 {ALLOWED_ROOT} 之外")
    return path


def set_workdir(new_dir):
    global ALLOWED_ROOT
    if not isinstance(new_dir, str) or not new_dir.strip():
        raise ValueError("请提供工作区路径")
    raw = Path(new_dir).expanduser()
    target = (raw if raw.is_absolute() else BASE_DIR / raw).resolve()
    check_policy(target)
    if BASE_DIR.is_relative_to(target):
        raise PermissionError("工作区不能包含正在运行的 OmyDs 项目")
    if not target.is_dir():
        raise ValueError("工作区必须是已存在的目录")
    ALLOWED_ROOT = target
    return str(target)


def reset_workdir():
    global ALLOWED_ROOT
    ALLOWED_ROOT = SANDBOX_ROOT
    return str(ALLOWED_ROOT)
