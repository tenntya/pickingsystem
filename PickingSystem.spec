# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\ui_desktop\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('src/templates', 'src/templates'), ('src/config/spec.yml', 'src/config'), ('.venv/Lib/site-packages/playwright/driver/package/.local-browsers', 'playwright/driver/package/.local-browsers')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PickingSystem',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PickingSystem',
)
