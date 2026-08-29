"""Minimal PyInstaller entry point for the existing application startup."""

from reimbursement_manager.app import main


if __name__ == "__main__":
    raise SystemExit(main())
