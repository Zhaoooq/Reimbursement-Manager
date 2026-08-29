from __future__ import annotations

import runpy
from pathlib import Path


def test_phase1_demo_creates_incomplete_item_and_prints_summary(
    tmp_path: Path, capsys
) -> None:
    script_path = Path(__file__).parents[1] / "scripts" / "demo_phase1.py"
    script = runpy.run_path(str(script_path))

    script["run_demo"](tmp_path / "demo-workspace")

    output = capsys.readouterr().out
    assert "树莓派 Zero 2 W" in output
    assert "Required: 4" in output
    assert "Completed: 3" in output
    assert "- 发票" in output
    assert "Completeness: 75%" in output
