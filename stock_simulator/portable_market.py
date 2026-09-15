"""Copy only the market files consumed by the application, never a TDX profile."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from .tdx_reader import DAY_RECORD, resolve_tdx_location

SUPPORT_FILES = ("gbbq", "shs.tnf", "szs.tnf", "base.dbf")
OPTIONAL_SUPPORT_FILES = ("bjs.tnf", "tdxzs.cfg", "tdxhy.cfg", "infoharbor_block.dat")


def copy_market_snapshot(source: str | Path, destination: Path) -> dict:
    location = resolve_tdx_location(source)
    if location is None:
        raise ValueError("没有有效的日K数据目录，请先选择完整通达信目录后再生成独立版。")
    hq = location.root / "T0002" / "hq_cache"
    missing = [name for name in SUPPORT_FILES if not (hq / name).is_file()]
    if missing:
        raise ValueError("数据目录缺少复权或股票资料：" + "、".join(missing) + "。请选择完整通达信目录。")
    sources = []
    for market, directory in location.day_dirs.items():
        for path in sorted(directory.glob("*.day")):
            sources.append((path, Path("vipdoc") / market / "lday" / path.name))
    if not sources:
        raise ValueError("数据目录没有日K文件。")
    day_count = len(sources)
    sources.extend((hq / name, Path("T0002/hq_cache") / name) for name in SUPPORT_FILES)
    sources.extend((hq / name, Path("T0002/hq_cache") / name)
                   for name in OPTIONAL_SUPPORT_FILES if (hq / name).is_file())
    files = []
    dates = []
    for source_path, relative in sources:
        before = source_path.stat()
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        data = target.read_bytes()
        after = source_path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("打包期间行情文件发生变化，请等待通达信下载完成后重试。")
        latest = None
        if relative.suffix == ".day":
            if len(data) % DAY_RECORD.size:
                raise ValueError(f"日K文件长度异常：{relative.name}")
            if data:
                date_number = DAY_RECORD.unpack_from(data, len(data) - DAY_RECORD.size)[0]
                latest = datetime.strptime(str(date_number), "%Y%m%d").strftime("%Y-%m-%d")
                dates.append(latest)
        files.append({"path": relative.as_posix(), "bytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest(), "last_date": latest})
    if not dates:
        raise ValueError("日K文件全部为空，无法生成可用的独立版。")
    manifest = {"version": 1, "created_at": datetime.now().isoformat(timespec="seconds"),
                "day_file_count": day_count, "latest_date": max(dates),
                "note": "最新日期为文件中的最大日期，各股票截止日期可能不同。", "files": files}
    (destination / "snapshot.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
