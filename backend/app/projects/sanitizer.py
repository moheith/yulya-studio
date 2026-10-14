"""
Security sanitizer and path validation rules for Yulya Studio V2.
Enforces strict sandbox isolation within data/projects/{user_id}/{slug}/ (Section 27).
"""

import re
from pathlib import Path
from typing import Tuple, List
from backend.app.core.config import settings
from backend.app.core.errors import AppError, ErrorCategory

# Dangerous escape and storage sniffing patterns in untrusted browser game code
DANGEROUS_PATTERNS = [
    re.compile(r'parent\.document', re.IGNORECASE),
    re.compile(r'top\.document', re.IGNORECASE),
    re.compile(r'window\.opener', re.IGNORECASE),
    re.compile(r'window\.parent', re.IGNORECASE),
    re.compile(r'window\.top', re.IGNORECASE),
    re.compile(r'document\.cookie', re.IGNORECASE),
    re.compile(r'localStorage', re.IGNORECASE),
    re.compile(r'sessionStorage', re.IGNORECASE),
    re.compile(r'indexedDB', re.IGNORECASE),
    re.compile(r'XMLHttpRequest', re.IGNORECASE),
    re.compile(r'fetch\s*\(', re.IGNORECASE),
    re.compile(r'eval\s*\(', re.IGNORECASE),
    re.compile(r'Function\s*\(', re.IGNORECASE),
]

RESERVED_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "LPT1", "LPT2"}


def sanitize_game_code(content: str) -> Tuple[str, List[str]]:
    """Neutralizes direct parent escape vectors while preserving playable game logic."""
    warnings: List[str] = []
    sanitized = content
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(sanitized):
            warnings.append(f"Neutralized risky pattern: {pattern.pattern}")
            sanitized = pattern.sub("/* blocked_security_rule */ null", sanitized)
    return sanitized, warnings


def validate_slug(slug: str) -> str:
    """Validates and returns a safe lowercase project slug."""
    if not slug or not isinstance(slug, str):
        raise AppError(ErrorCategory.INVALID_INPUT, "Project slug is required.")

    if any(p in slug for p in ["..", "/", "\\", "%", "\0", ":"]):
        raise AppError(ErrorCategory.PERMISSION_DENIED, "Path traversal attempt detected in slug.")

    # Convert whitespace sequences to single hyphens
    slug_hyphenated = re.sub(r'\s+', '-', slug.strip())
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug_hyphenated).lower()
    safe_slug = re.sub(r'-+', '-', safe_slug).strip('-')
    if not safe_slug:
        raise AppError(ErrorCategory.INVALID_INPUT, "Invalid slug: empty after sanitization.")

    if safe_slug.upper() in RESERVED_DEVICE_NAMES:
        raise AppError(ErrorCategory.PERMISSION_DENIED, f"Reserved system device name in slug: {safe_slug}")

    return safe_slug


def resolve_project_path(user_id: int, slug: str) -> Path:
    """
    Resolves project root directory and strictly verifies containment inside config.PROJECTS_DIR/{user_id}/{slug}.
    """
    try:
        user_id_int = int(user_id)
        if user_id_int <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise AppError(ErrorCategory.AUTHENTICATION, "Invalid user ID: must be a positive integer.")

    safe_slug = validate_slug(slug)
    base_root = settings.PROJECTS_DIR.resolve()
    user_root = (base_root / str(user_id_int)).resolve()
    project_dir = (user_root / safe_slug).resolve()

    try:
        project_dir.relative_to(user_root)
        project_dir.relative_to(base_root)
    except ValueError:
        raise AppError(ErrorCategory.PERMISSION_DENIED, "Path traversal attempt detected: escapes user directory.")

    if project_dir == user_root or project_dir == base_root:
        raise AppError(ErrorCategory.PERMISSION_DENIED, "Cannot access root directory.")

    return project_dir


def resolve_file_path(project_dir: Path, relative_path: str) -> Path:
    """
    Resolves an individual file within the project directory.
    Enforces extension allowlist, protected files check, and strict containment.
    """
    if not relative_path or not isinstance(relative_path, str):
        raise AppError(ErrorCategory.INVALID_INPUT, "File path is required.")

    raw_path = relative_path.strip()
    if raw_path.startswith("/") or raw_path.startswith("\\") or Path(raw_path).is_absolute() or ":" in raw_path:
        raise AppError(ErrorCategory.PERMISSION_DENIED, "Absolute paths and drive letters are strictly forbidden.")

    clean_rel = raw_path.replace("\\", "/").lstrip("/")

    if any(p in clean_rel for p in ["..", "%", "\0"]):
        raise AppError(ErrorCategory.PERMISSION_DENIED, "Path traversal attempt detected in file path.")

    # Check path depth
    depth = len(clean_rel.split("/"))
    if depth > settings.MAX_NESTED_PATH_DEPTH:
        raise AppError(ErrorCategory.PERMISSION_DENIED, f"Exceeded maximum path depth limit ({settings.MAX_NESTED_PATH_DEPTH}).")

    target_path = (project_dir / clean_rel).resolve()

    try:
        target_path.relative_to(project_dir)
    except ValueError:
        raise AppError(ErrorCategory.PERMISSION_DENIED, "Path traversal attempt detected: file escapes project root.")

    filename = target_path.name
    if filename in settings.PROTECTED_FILENAMES:
        raise AppError(ErrorCategory.PERMISSION_DENIED, f"Access to protected file '{filename}' is forbidden.")

    ext = target_path.suffix.lower()
    if ext in settings.DISALLOWED_EXTENSIONS:
        raise AppError(ErrorCategory.PERMISSION_DENIED, f"File extension '{ext}' is forbidden.")

    # Allow extensionless folders during creation; otherwise require allowed extensions for files
    if ext and ext not in settings.ALLOWED_GAME_EXTENSIONS:
        raise AppError(ErrorCategory.PERMISSION_DENIED, f"File extension '{ext}' is not in approved game assets allowlist.")

    return target_path


def is_safe_game_file(filename: str) -> bool:
    """Checks whether a filename matches permitted extensions and is not a protected system file."""
    if not filename or filename in settings.PROTECTED_FILENAMES:
        return False
    path = Path(filename)
    ext = path.suffix.lower()
    if not ext or ext in settings.DISALLOWED_EXTENSIONS:
        return False
    return ext in settings.ALLOWED_GAME_EXTENSIONS
