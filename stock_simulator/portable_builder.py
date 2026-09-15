from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import AppSettings, PORTABLE_DATA_DIR_NAME, PORTABLE_MARKER_FILE_NAME
from .data_migration import FIXED_CACHE_FILE_NAMES, MIGRATABLE_FILE_NAMES
from .config import PORTABLE_MARKET_DIR_NAME, resolve_market_setting
from .portable_market import copy_market_snapshot


PORTABLE_RELEASE_NAME = "大A日K股票模拟训练器-独立便携版"
PORTABLE_EXECUTABLE_NAME = "大A日K股票模拟训练器.exe"
PORTABLE_SPEC_FILE_NAME = "日K模拟炒股训练器-便携版.spec"


@dataclass(frozen=True)
class PortableBuildResult:
    directory: Path
    copied_data_files: tuple[str, ...]
    mode: str


def build_portable_folder(
    destination_parent: Path,
    user_data_root: Path,
    *,
    project_root: Path | None = None,
    python_executable: Path | None = None,
    frozen: bool | None = None,
    executable_path: Path | None = None,
    market_source: str | Path | None = None,
    include_market_data: bool = True,
) -> PortableBuildResult:
    destination = Path(destination_parent)
    destination.mkdir(parents=True, exist_ok=True)
    release_name = PORTABLE_RELEASE_NAME if include_market_data else "大A日K股票模拟训练器-便携版-无行情"
    target = _available_directory(destination / release_name)
    packaged = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    workspace = Path(tempfile.mkdtemp(prefix=".portable-build-", dir=destination))
    staged_release = workspace / "release"
    data_snapshot = workspace / "data_snapshot"
    try:
        if include_market_data and market_source is None:
            settings_file = Path(user_data_root) / "settings.json"
            if not settings_file.is_file():
                raise ValueError("没有数据源设置，请先选择通达信数据目录。")
            settings = json.loads(settings_file.read_text(encoding="utf-8-sig"))
            raw_source = settings.get("tdx_root", "") if isinstance(settings, dict) else None
            if not isinstance(raw_source, str) or not raw_source.strip():
                raise ValueError("没有有效的数据源设置，请先选择数据目录。")
            market_source = Path(raw_source)
            if not market_source.is_absolute():
                market_source = Path(user_data_root).resolve().parent / market_source
        snapshot = workspace / "market_snapshot"
        if include_market_data:
            copy_market_snapshot(market_source, snapshot)
        _prepare_clean_portable_data(Path(user_data_root), data_snapshot, include_market_data=include_market_data)
        if packaged:
            source_executable = Path(executable_path or sys.executable).resolve()
            if not source_executable.is_file():
                raise FileNotFoundError("找不到当前 EXE，无法生成便携版。")
            staged_release.mkdir()
            shutil.copy2(source_executable, staged_release / PORTABLE_EXECUTABLE_NAME)
            _copy_frozen_runtime_dependencies(source_executable.parent, staged_release)
            mode = "exe"
        else:
            source_root = Path(project_root or Path(__file__).resolve().parent.parent).resolve()
            spec_path = source_root / PORTABLE_SPEC_FILE_NAME
            if not spec_path.is_file():
                raise FileNotFoundError(f"找不到便携版打包配置：{spec_path}")
            python = Path(python_executable or sys.executable).resolve()
            dist_path = workspace / "dist"
            work_path = workspace / "build"
            command = [
                str(python),
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(dist_path),
                "--workpath",
                str(work_path),
                str(spec_path),
            ]
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            completed = subprocess.run(
                command,
                cwd=source_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "未知错误").strip()
                raise RuntimeError(f"便携版依赖打包失败：\n{detail[-4000:]}")
            built = dist_path / "大A日K股票模拟训练器"
            if not (built / PORTABLE_EXECUTABLE_NAME).is_file():
                raise RuntimeError("便携版依赖已打包，但未找到启动程序。")
            shutil.move(str(built), staged_release)
            mode = "source"

        copied = _write_portable_files(staged_release, data_snapshot, include_market_data=include_market_data)
        if include_market_data:
            shutil.move(str(snapshot), str(staged_release / PORTABLE_MARKET_DIR_NAME))
        shutil.move(str(staged_release), str(target))
        return PortableBuildResult(target, copied, mode)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _write_portable_files(release_root: Path, source_data_root: Path, *, include_market_data: bool = True) -> tuple[str, ...]:
    (release_root / PORTABLE_MARKER_FILE_NAME).write_text(
        "portable data stays beside the application\n",
        encoding="utf-8",
    )
    portable_data = release_root / PORTABLE_DATA_DIR_NAME
    portable_data.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in (*MIGRATABLE_FILE_NAMES, *FIXED_CACHE_FILE_NAMES):
        source = source_data_root / name
        if not source.is_file():
            continue
        shutil.copy2(source, portable_data / name)
        copied.append(name)
    (release_root / "运行.bat").write_text(
        "@echo off\r\n"
        'cd /d "%~dp0"\r\n'
        "for %%F in (*.exe) do (\r\n"
        '  start "" "%%~fF"\r\n'
        "  exit /b 0\r\n"
        ")\r\n"
        "echo Application executable not found.\r\n"
        "pause\r\n"
        "exit /b 1\r\n",
        encoding="ascii",
    )
    instructions = (
        "大A日K股票模拟训练器 - 免安装便携版\n\n"
        "1. 整个文件夹可直接复制到另一台 Windows 电脑。\n"
        "2. 双击“运行.bat”即可启动，不需要安装 Python、PySide6 或其他依赖。\n"
        "3. 首次启动默认为连续复利模式、关闭全部均线、显示成交量和 MACD 两个副图。\n"
        "4. 首次打开自动使用 market_data 中的个股/板块指数日K、复权、股票资料及行业、概念、风格名单，无需安装通达信。\n"
        "5. 这是可分发的干净版本，不包含制作者的续作会话或历史成绩。\n"
        "6. 后续设置和训练记录保存在 portable_data 文件夹，请勿单独删除。\n"
        "7. 内置个股行情不会自动更新，各股票截止日期见 market_data/snapshot.json。\n"
        "   可通过“模拟 → 选择通达信目录”接回外部数据，再通过“使用内置历史数据”切回。\n"
        "   上证指数保留原有联网更新能力；断网仍可使用内置历史数据。\n"
        "8. 桌面上单独导出的截图、Excel 和 CSV 不属于软件内部数据，请按需自行复制。\n"
    )
    if not include_market_data:
        instructions = (
            "大A日K股票模拟训练器 - 便携版（不包含通达信行情）\n\n"
            "1. 解压整个文件夹，双击“运行.bat”或EXE启动，无需安装Python。\n"
            "2. 本包不包含通达信行情、权息或板块/股票资料，也不包含个人成绩和续作存档。\n"
            "3. 个股训练请通过“模拟 → 选择通达信目录”连接你自己的通达信。\n"
            "4. 保留内置上证指数和测试K线，设置、缓存、训练记录保存在 portable_data。\n"
            "5. 行业、概念和风格需要通达信目录中对应的板块基础资料及板块日K。\n"
            "6. 搬迁时保留整个文件夹和_internal依赖目录。\n"
        )
    (release_root / "便携版说明.txt").write_text(instructions, encoding="utf-8-sig")
    return tuple(copied)


def _prepare_clean_portable_data(source_data_root: Path, target_data_root: Path, *, include_market_data: bool = True) -> tuple[str, ...]:
    """Create default settings without personal sessions or performance records."""
    target_data_root.mkdir(parents=True, exist_ok=True)
    settings_path = target_data_root / "settings.json"
    settings_path.write_text(
        json.dumps(asdict(AppSettings(tdx_root=PORTABLE_MARKET_DIR_NAME if include_market_data else "")), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # The packaged application seeds its own bundled index and market overview
    # on first launch.  Do not copy the author's refreshed caches, corporate
    # action data, stock selection, session or history into a public package.
    return ("settings.json",)


def _copy_frozen_runtime_dependencies(source_dir: Path, target_dir: Path) -> None:
    """Preserve PyInstaller onedir dependencies during a second export."""

    internal_dir = source_dir / "_internal"
    if internal_dir.is_dir():
        shutil.copytree(internal_dir, target_dir / "_internal", dirs_exist_ok=True)


def _available_directory(preferred: Path) -> Path:
    if not preferred.exists():
        return preferred
    suffix = 2
    while True:
        candidate = preferred.with_name(f"{preferred.name}-{suffix}")
        if not candidate.exists():
            return candidate
        suffix += 1
