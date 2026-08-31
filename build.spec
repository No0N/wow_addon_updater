# PyInstaller spec для сборки exe
# Команда: pyinstaller build.spec
# Иконка: положи icon.ico в папку проекта или создай из SVG: python build_icon.py

import os
# Если icon.ico есть — подставляем в exe; иначе собираем без иконки
has_icon = os.path.isfile('icon.ico')

a = Analysis(
    ['main.py'],  # gui, config, tukui подтянутся по импортам
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna',
        'cryptography', 'pygame', 'PIL', 'numpy',
    ],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure)

exe_options = dict(
    name='ElvUI_Updater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
if has_icon:
    exe_options['icon'] = 'icon.ico'

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    **exe_options,
)
