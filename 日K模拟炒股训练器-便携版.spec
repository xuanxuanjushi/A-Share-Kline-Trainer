# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('stock_simulator\\assets', 'stock_simulator\\assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# The overview cache contains distributor source paths; each user builds their
# own statistics only after choosing their TDX directory.
a.datas = [entry for entry in a.datas
           if entry[0].replace('\\', '/') != 'stock_simulator/assets/market_stats_daily.json']
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='大A日K股票模拟训练器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=['stock_simulator\\assets\\app_icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='大A日K股票模拟训练器',
)
