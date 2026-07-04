# applied to every path from users, the agent, and the compiler. Project file paths are logical, not host paths

import re

# PurePosixPath parses logical project paths consistently across different os
from pathlib import PurePosixPath

# allow ordinary repo/project file names, no spaces keeps URL/path handling simple
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

class UnsafePathError(ValueError):
    pass


def sanitize_project_path(path:str) -> str:
    # null bytes are a classic filesystem attack/input-corruption vector
    if "\x00" in path:
        raise UnsafePathError("path contains null byte")
    
    # backslashes behave differently in windows and can hide traversal intent
    if "\\" in path:
        raise UnsafePathError("backslashes are not allowed")
    
    # project files must be relative, never abs host paths
    if path.startswith("/"):
        raise UnsafePathError("absolute paths are not allowed")
    
    # parse as POSIX path cuz project paths are logical, not OS-native
    pure = PurePosixPath(path)

    if any(part in {"", ".", ".."} for part in pure.parts):
        raise UnsafePathError("empty, current, or parent path segments are not allowed")
    
    # Hidden files like `.env` should never be exposed to the agent/compiler.
    if any(part.startswith(".") for part in pure.parts):
        raise UnsafePathError("hidden files are not allowed")
    
    return str(pure)


# sanitizer is used for file CRUD, inspect tools, patch tools, and compiler writes
# it protects both the host filesystems and project boundaries
# it intentionally accepts a small path language so future behavior is predictable