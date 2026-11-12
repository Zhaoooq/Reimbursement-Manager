"""Relocatable PyInstaller configuration for the Windows onedir bundle."""

from __future__ import annotations

from pathlib import Path
import ssl


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
        str(SOURCE_ROOT / "reimbursement_manager" / "ui" / "resources"),
        "reimbursement_manager/ui/resources",
    ),
    (
        str(SOURCE_ROOT / "reimbursement_manager" / "database" / "migrations"),
        "reimbursement_manager/database/migrations",
    ),
]

# Some Windows Python distributions patch ``ssl.py`` to distrust specific roots
# and load an extra PEM from the stdlib directory.  Frozen builds keep ``ssl.py``
# inside the bundle, so that file has to sit next to it or *every* TLS context
# fails to construct.  Harmless when the patched runtime is not in use.
_rejected_ca_bundle = Path(ssl.__file__).parent / "codex-rejected-cas.pem"
if _rejected_ca_bundle.is_file():
    datas.append((str(_rejected_ca_bundle), "."))

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
