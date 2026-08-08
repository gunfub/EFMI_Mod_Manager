# -*- mode: python ; coding: utf-8 -*-

# keyring 通过包内后端插件发现（Windows 凭据管理器），需完整打包
from PyInstaller.utils.hooks import collect_all

_keyring_datas, _keyring_binaries, _keyring_hidden = collect_all('keyring')

a = Analysis(
    ['mod_manager.py'],
    pathex=[],
    binaries=[] + _keyring_binaries,
    datas=[] + _keyring_datas,
    hiddenimports=[] + _keyring_hidden,
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
    name='EFMI_Mod_Manager_v2.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EFMI_Mod_Manager_v2.0',
)
