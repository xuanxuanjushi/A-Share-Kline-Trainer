"""Preserve damaged user files before a fallback can overwrite them."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)
_blocked_paths: set[Path] = set()
_notices: dict[Path, str] = {}


def preserve_invalid_file(path: Path) -> None:
    backup = path.with_name(f"{path.name}.invalid-{uuid4().hex}.bak")
    try:
        shutil.copy2(path, backup)
    except OSError:
        _blocked_paths.add(path.resolve())
        _notices[path.resolve()] = f"{path.name} 数据异常且无法备份，已禁止覆盖，请检查文件权限。"
        logger.warning("数据文件读取异常且无法备份；已禁止覆盖：%s", path.name)
    else:
        _blocked_paths.discard(path.resolve())
        _notices[path.resolve()] = f"{path.name} 数据异常，已保留备份 {backup.name}，请在数据目录检查。"
        logger.warning("数据文件异常，原件已备份：%s", backup.name)


def ensure_writable(path: Path) -> None:
    if path.resolve() in _blocked_paths:
        raise OSError(f"{path.name} 数据异常且未能备份，为保护原件已停止写入。")


def consume_storage_notices(root: Path) -> list[str]:
    return [_notices.pop(path) for path in list(_notices) if path.parent == root.resolve()]
