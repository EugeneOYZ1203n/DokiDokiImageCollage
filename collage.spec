# PyInstaller spec: onedir, windowed (no console).  Build with build.ps1
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

a = Analysis(
    ["run_collage.py"],
    pathex=["."],
    binaries=[],
    # cv2.data.haarcascades is read at runtime by collage/saliency.py (face detection)
    datas=collect_data_files("cv2"),
    hiddenimports=["PIL.ImageTk", "scipy.optimize"],
    excludes=["matplotlib", "pytest", "IPython", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DokiDokiCollage",
    console=False,  # --noconsole
    disable_windowed_traceback=False,
    # icon="assets/icon.ico",  # add an .ico and uncomment
)
coll = COLLECT(exe, a.binaries, a.datas, name="DokiDokiCollage")
