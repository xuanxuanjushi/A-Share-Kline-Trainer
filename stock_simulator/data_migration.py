from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config as config_module


MIGRATION_FORMAT_VERSION = 1
MIGRATION_MANIFEST_NAME = "migration_manifest.json"
MIGRATABLE_FILE_NAMES = (
    "settings.json",
    "session_state.json",
    "performance_history.json",
)
FIXED_CACHE_FILE_NAMES = (
    "shanghai_index_daily.json",
    "market_stats_daily.json",
    "gbbq_events.json",
    "gbbq_events.bin",
)
ADJUSTED_CACHE_DIR_NAME = "adjusted_bars_cache"
CACHE_MAINTENANCE_FILE_NAME = "cache_maintenance.json"
MIGRATION_BACKUP_DIR_NAME = "migration_backups"
DEFAULT_ADJUSTED_CACHE_LIMIT_BYTES = 256 * 1024 * 1024
DEFAULT_CACHE_MAINTENANCE_INTERVAL_SECONDS = 7 * 24 * 60 * 60
MAX_MIGRATION_FILE_BYTES = 64 * 1024 * 1024
MAX_MIGRATION_TOTAL_BYTES = 128 * 1024 * 1024


class MigrationPackageError(ValueError):
    pass


@dataclass(frozen=True)
class MigrationImportResult:
    imported_files: tuple[str, ...]
    backup_directory: Path | None


@dataclass(frozen=True)
class CacheCleanupResult:
    scanned_files: int
    kept_files: int
    removed_files: int
    removed_bytes: int
    remaining_bytes: int
    skipped: bool = False


@dataclass(frozen=True)
class StorageUsage:
    user_data_bytes: int
    cache_bytes: int
    migration_backup_bytes: int
    other_bytes: int
    user_file_count: int
    cache_file_count: int

    @property
    def total_bytes(self) -> int:
        return self.user_data_bytes + self.cache_bytes + self.migration_backup_bytes + self.other_bytes


def user_data_root(root: Path | None = None) -> Path:
    return Path(root) if root is not None else config_module.CONFIG_PATH.parent


def export_migration_package(destination: Path, root: Path | None = None) -> Path:
    source_root = user_data_root(root)
    target = Path(destination)
    if target.suffix.lower() != ".zip":
        target = target.with_name(f"{target.name}.zip")
    target.parent.mkdir(parents=True, exist_ok=True)

    payloads: dict[str, bytes] = {}
    manifest_files: list[dict[str, object]] = []
    total_size = 0
    for name in MIGRATABLE_FILE_NAMES:
        path = source_root / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if len(data) > MAX_MIGRATION_FILE_BYTES:
            raise MigrationPackageError(f"{name} 超过迁移包单文件大小限制。")
        _validate_json_document(name, data)
        total_size += len(data)
        if total_size > MAX_MIGRATION_TOTAL_BYTES:
            raise MigrationPackageError("用户数据总量超过迁移包大小限制。")
        payloads[name] = data
        manifest_files.append(
            {
                "name": name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    if not payloads:
        raise MigrationPackageError("没有找到可打包的用户数据。")

    manifest = {
        "format_version": MIGRATION_FORMAT_VERSION,
        "application": "大A日K股票模拟训练器",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": manifest_files,
        "excluded": ["通达信原始行情", "可重建行情缓存", "桌面截图和CSV"],
    }
    file_handle, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}-",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(file_handle)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                MIGRATION_MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            for name, data in payloads.items():
                archive.writestr(f"data/{name}", data)
        os.replace(temporary, target)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return target


def inspect_migration_package(package_path: Path) -> dict[str, bytes]:
    package = Path(package_path)
    if not package.is_file():
        raise MigrationPackageError("迁移包不存在。")
    try:
        with zipfile.ZipFile(package, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise MigrationPackageError("迁移包包含重复文件。")
            if MIGRATION_MANIFEST_NAME not in names:
                raise MigrationPackageError("迁移包缺少清单文件。")
            manifest_info = archive.getinfo(MIGRATION_MANIFEST_NAME)
            if manifest_info.file_size > 1024 * 1024:
                raise MigrationPackageError("迁移包清单异常。")
            try:
                manifest = json.loads(archive.read(manifest_info).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
                raise MigrationPackageError("迁移包清单无法读取。") from exc
            if not isinstance(manifest, dict) or manifest.get("format_version") != MIGRATION_FORMAT_VERSION:
                raise MigrationPackageError("迁移包版本不受支持。")
            rows = manifest.get("files")
            if not isinstance(rows, list) or not rows:
                raise MigrationPackageError("迁移包没有用户数据。")

            payloads: dict[str, bytes] = {}
            expected_entries = {MIGRATION_MANIFEST_NAME}
            total_size = 0
            for row in rows:
                if not isinstance(row, dict):
                    raise MigrationPackageError("迁移包文件清单格式错误。")
                name = row.get("name")
                if name not in MIGRATABLE_FILE_NAMES or name in payloads:
                    raise MigrationPackageError("迁移包包含不允许的数据文件。")
                entry_name = f"data/{name}"
                expected_entries.add(entry_name)
                if entry_name not in names:
                    raise MigrationPackageError(f"迁移包缺少 {name}。")
                info = archive.getinfo(entry_name)
                if info.is_dir() or info.file_size > MAX_MIGRATION_FILE_BYTES:
                    raise MigrationPackageError(f"{name} 大小异常。")
                total_size += info.file_size
                if total_size > MAX_MIGRATION_TOTAL_BYTES:
                    raise MigrationPackageError("迁移包数据总量异常。")
                data = archive.read(info)
                if row.get("size") != len(data) or row.get("sha256") != hashlib.sha256(data).hexdigest():
                    raise MigrationPackageError(f"{name} 校验失败，文件可能已损坏。")
                _validate_json_document(str(name), data)
                payloads[str(name)] = data
            if set(names) != expected_entries:
                raise MigrationPackageError("迁移包包含清单之外的文件。")
            return payloads
    except zipfile.BadZipFile as exc:
        raise MigrationPackageError("所选文件不是有效的迁移包。") from exc


def import_migration_package(package_path: Path, root: Path | None = None) -> MigrationImportResult:
    payloads = inspect_migration_package(package_path)
    target_root = user_data_root(root)
    target_root.mkdir(parents=True, exist_ok=True)
    existing_names = [name for name in MIGRATABLE_FILE_NAMES if (target_root / name).is_file()]
    backup_directory = _create_import_backup(target_root, existing_names) if existing_names else None

    written_names: list[str] = []
    try:
        for name, data in payloads.items():
            _atomic_write_bytes(target_root / name, data)
            written_names.append(name)
    except Exception:
        _roll_back_import(target_root, written_names, existing_names, backup_directory)
        raise
    return MigrationImportResult(tuple(written_names), backup_directory)


def calculate_storage_usage(root: Path | None = None) -> StorageUsage:
    base = user_data_root(root)
    if not base.exists():
        return StorageUsage(0, 0, 0, 0, 0, 0)
    user_names = set(MIGRATABLE_FILE_NAMES)
    fixed_cache_names = set(FIXED_CACHE_FILE_NAMES) | {CACHE_MAINTENANCE_FILE_NAME}
    user_bytes = cache_bytes = backup_bytes = other_bytes = 0
    user_count = cache_count = 0
    backup_root = base / MIGRATION_BACKUP_DIR_NAME
    adjusted_root = base / ADJUSTED_CACHE_DIR_NAME
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if path.parent == base and path.name in user_names:
            user_bytes += size
            user_count += 1
        elif path.parent == base and path.name in fixed_cache_names:
            cache_bytes += size
            cache_count += 1
        elif _is_relative_to(path, adjusted_root):
            cache_bytes += size
            cache_count += 1
        elif _is_relative_to(path, backup_root):
            backup_bytes += size
        else:
            other_bytes += size
    return StorageUsage(user_bytes, cache_bytes, backup_bytes, other_bytes, user_count, cache_count)


def trim_adjusted_bars_cache(
    root: Path | None = None,
    max_bytes: int = DEFAULT_ADJUSTED_CACHE_LIMIT_BYTES,
) -> CacheCleanupResult:
    cache_root = user_data_root(root) / ADJUSTED_CACHE_DIR_NAME
    if not cache_root.exists():
        return CacheCleanupResult(0, 0, 0, 0, 0)
    candidates: list[tuple[float, int, Path]] = []
    removed_files = 0
    removed_bytes = 0
    for path in cache_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if path.suffix.lower() == ".tmp":
            try:
                path.unlink()
                removed_files += 1
                removed_bytes += stat.st_size
            except OSError:
                pass
            continue
        candidates.append((stat.st_mtime, stat.st_size, path))
    candidates.sort(key=lambda item: item[0], reverse=True)
    remaining_bytes = 0
    kept_files = 0
    for _modified, size, path in candidates:
        if remaining_bytes + size <= max(0, int(max_bytes)):
            remaining_bytes += size
            kept_files += 1
            continue
        try:
            path.unlink()
            removed_files += 1
            removed_bytes += size
        except OSError:
            remaining_bytes += size
            kept_files += 1
    _remove_empty_directories(cache_root)
    return CacheCleanupResult(
        scanned_files=len(candidates),
        kept_files=kept_files,
        removed_files=removed_files,
        removed_bytes=removed_bytes,
        remaining_bytes=remaining_bytes,
    )


def clear_adjusted_bars_cache(root: Path | None = None) -> CacheCleanupResult:
    return trim_adjusted_bars_cache(root, max_bytes=0)


def run_scheduled_cache_maintenance(
    root: Path | None = None,
    *,
    now: float | None = None,
    interval_seconds: int = DEFAULT_CACHE_MAINTENANCE_INTERVAL_SECONDS,
    max_bytes: int = DEFAULT_ADJUSTED_CACHE_LIMIT_BYTES,
) -> CacheCleanupResult:
    base = user_data_root(root)
    marker = base / CACHE_MAINTENANCE_FILE_NAME
    current_time = time.time() if now is None else float(now)
    try:
        document = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
        last_run = float(document.get("last_run", 0.0)) if isinstance(document, dict) else 0.0
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        last_run = 0.0
    if current_time - last_run < max(0, int(interval_seconds)):
        return CacheCleanupResult(0, 0, 0, 0, 0, skipped=True)
    result = trim_adjusted_bars_cache(base, max_bytes=max_bytes)
    try:
        base.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(
            marker,
            json.dumps(
                {
                    "last_run": current_time,
                    "limit_bytes": int(max_bytes),
                    "remaining_bytes": result.remaining_bytes,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
    except OSError:
        pass
    return result


def _validate_json_document(name: str, data: bytes) -> None:
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationPackageError(f"{name} 不是有效的 JSON 数据。") from exc
    if not isinstance(document, dict):
        raise MigrationPackageError(f"{name} 数据结构不正确。")


def _create_import_backup(target_root: Path, names: list[str]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = target_root / MIGRATION_BACKUP_DIR_NAME
    backup = base / timestamp
    suffix = 2
    while backup.exists():
        backup = base / f"{timestamp}-{suffix}"
        suffix += 1
    backup.mkdir(parents=True, exist_ok=False)
    for name in names:
        shutil.copy2(target_root / name, backup / name)
    return backup


def _roll_back_import(
    target_root: Path,
    written_names: list[str],
    existing_names: list[str],
    backup_directory: Path | None,
) -> None:
    existing = set(existing_names)
    for name in written_names:
        target = target_root / name
        try:
            if name in existing and backup_directory is not None:
                _atomic_write_bytes(target, (backup_directory / name).read_bytes())
            else:
                target.unlink()
        except OSError:
            pass


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _remove_empty_directories(root: Path) -> None:
    directories = sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True)
    for path in directories:
        try:
            path.rmdir()
        except OSError:
            pass


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
