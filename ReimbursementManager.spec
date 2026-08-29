"""Relocatable PyInstaller configuration for the Windows onedir bundle."""

from __future__ import annotations

from pathlib import Path


# PyInstaller executes specs without ``__file__``; SPECPATH is the directory
# containing this spec and remains valid after moving the project checkout.
PROJECT_ROOT = Path(SPECPATH).resolve()
SOURCE_ROOT = PROJECT_ROOT / "src"

# These are the source files loaded from disk by the frozen application.  Keep
# their bundle locations aligned with runtime_resources.py and theme.py.
datas = [
    (str(PROJECT_ROOT / "alembic.ini"), "."),
    (
        str(SOURCE_ROOT / "reimbursement_manager" / "ui" / "styles"),
        "reimbursement_manager/ui/styles",
    ),
    (
        str(SOURCE_ROOT / "reimbursement_manager" / "database" / "migrations"),
        "reimbursement_manager/database/migrations",
    ),
]

a = Analysis(
    [str(PROJECT_ROOT / "scripts" / "build_entry.py")],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=["logging.config"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ReimbursementManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ReimbursementManager",
)
