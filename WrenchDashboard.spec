# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all
import os

block_cipher = None

# 🔥 Collect all bokeh + tornado dependencies
bokeh_data = collect_all('bokeh')
tornado_data = collect_all('tornado')
jinja2_data = collect_all('jinja2')

# Find logo files (if they exist)
logo_files = []
for pattern in ['*Bhabha_Atomic_Research_Centre_Logo*.*', '*DRHR Logo_withoutbg*.*']:
    # Add your logo files here if they exist
    # logo_files.append(('path/to/logo.png', '.'))
    pass

a = Analysis(
    ['dashboard_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('realtime_wrench_bokeh.py', '.'),
    ] + bokeh_data[0] + tornado_data[0] + jinja2_data[0] + logo_files,
    
    hiddenimports=[
        'bokeh.server.server',
        'bokeh.application',
        'bokeh.application.handlers.script',
        'bokeh.models',
        'bokeh.layouts',
        'bokeh.plotting',
        'tornado',
        'tornado.ioloop',
        'tornado.web',
        'jinja2',
        'jinja2.ext',
        'numpy',
        'pandas',
        'csv',
        'socket',
        'threading',
        'base64',
        'pathlib',
        'datetime',
    ] + bokeh_data[2] + tornado_data[2] + jinja2_data[2],

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'tkinter', 'PyQt5', 'PyQt6'],
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
    icon=None,  # Add icon='path/to/icon.ico' if you have one
)
