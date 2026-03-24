# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Collect all pandas files without deep analysis
pandas_datas, pandas_binaries, pandas_hiddenimports = collect_all('pandas')

a = Analysis(
    ['dashboard_launcher.py'],
    pathex=[],
    binaries=pandas_binaries,  # ← Add pandas binaries
    datas=[
        ('realtime_wrench_bokeh.py', '.'),
    ] + pandas_datas,  # ← Add pandas data files
    hiddenimports=[
        # Bokeh server
        'bokeh.server.server',
        'bokeh.application',
        'bokeh.application.application',
        'bokeh.application.handlers',
        'bokeh.application.handlers.script',
        'bokeh.application.handlers.code',
        # Core Bokeh
        'bokeh.models',
        'bokeh.plotting',
        'bokeh.layouts',
        # Dependencies
        'tornado',
        'tornado.ioloop',
        'numpy',
        'jinja2',
        'webbrowser',
    ] + pandas_hiddenimports,  # ← Add pandas hidden imports
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'IPython',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='WrenchDashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)