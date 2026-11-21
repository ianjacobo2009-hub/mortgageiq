# PyInstaller spec: builds MortgageIQ.app (macOS) or MortgageIQ.exe (Windows)
import sys
a = Analysis(["run_mortgageiq.py"], pathex=["."], datas=[("assets", "assets")],
             hiddenimports=["PySide6.QtPrintSupport"],
             excludes=["tkinter", "matplotlib", "IPython", "pytest", "scipy", "pandas", "numpy"])
pyz = PYZ(a.pure)
icon = "assets/icon.icns" if sys.platform == "darwin" else None
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MortgageIQ", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="MortgageIQ")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="MortgageIQ.app", icon=icon, bundle_identifier="com.bluepeak.mortgageiq",
                 info_plist={"CFBundleShortVersionString": "2.0.0", "NSHighResolutionCapable": True})
