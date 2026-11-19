from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SANDBOX_ROOT = BASE_DIR / "sandbox"
SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
ALLOWED_ROOT = SANDBOX_ROOT
STATE_ROOT = Path.home() / ".omyds"

# These are safeguards for explicit OUTSIDE-file exceptions, not a shell sandbox.
FORBIDDEN_NAMES = {"config.toml", ".env", ".ssh", ".gnupg", "id_rsa", "id_ed25519", "agent.md"}
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
    """Disallow selecting system directories, app code, or client session state."""
    if path == Path("/") or any(path.is_relative_to(p.resolve()) for p in SYSTEM_ROOTS):
        raise PermissionError("工作区模式不允许访问系统目录")
    if path.is_relative_to(BASE_DIR) and not path.is_relative_to(SANDBOX_ROOT):
        raise PermissionError("工作区模式不允许访问正在运行的 OmyDs；请使用独立工作副本")
    if path.is_relative_to(STATE_ROOT.resolve()):
        raise PermissionError("工作区模式不允许访问 OmyDs 会话与记忆目录")


def validate_path(user_path, allow_outside=False, host=False):
    path = resolve_path(user_path)
    if host:
        return path  # Explicit host mode: the OS current-user permissions apply.
    check_policy(path)
    if path.is_relative_to(ALLOWED_ROOT):
        return path  # Entire selected workspace is trusted, including dotfiles.
    if any(part in FORBIDDEN_NAMES for part in path.parts) or path.suffix in {".key", ".pem"}:
        raise PermissionError("单次越界授权不包含此敏感文件；请手动处理")
    if not allow_outside:
        raise OutOfSandboxError(f"目标 {path} 位于工作区 {ALLOWED_ROOT} 之外")
    return path


def set_workdir(new_dir):
    global ALLOWED_ROOT
    if not isinstance(new_dir, str) or not new_dir.strip():
        raise ValueError("请提供工作区路径")
    raw = Path(new_dir).expanduser()
    # User-typed relative paths refer to where OmyDs was launched.
    target = (raw if raw.is_absolute() else Path.cwd() / raw).resolve()
    check_policy(target)
    if BASE_DIR.is_relative_to(target) or STATE_ROOT.resolve().is_relative_to(target):
        raise PermissionError("工作区不能包含 OmyDs 程序或其会话/记忆目录")
    if not target.is_dir():
        raise ValueError("工作区必须是已存在的目录")
    ALLOWED_ROOT = target
    return str(target)


def reset_workdir():
    global ALLOWED_ROOT
    ALLOWED_ROOT = SANDBOX_ROOT
    return str(ALLOWED_ROOT)
