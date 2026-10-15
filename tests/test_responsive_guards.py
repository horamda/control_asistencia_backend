"""Guardas de responsividad sobre las plantillas (sin navegador)."""
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
# minmax con minimo fijo >= 200px fuera de auto-fit/auto-fill no se adapta.
RIGID_GRID = re.compile(r"grid-template-columns\s*:\s*(?![^;\"]*auto-(?:fit|fill))[^;\"]*minmax\(\s*([0-9]{3,4})px")


def test_inline_grids_adapt_to_narrow_screens():
    offenders = []
    for path in TEMPLATES.rglob("*.html"):
        for match in RIGID_GRID.finditer(path.read_text(encoding="utf-8")):
            if int(match.group(1)) >= 200:
                offenders.append(f"{path.relative_to(TEMPLATES)}: {match.group(0)}")
    assert offenders == [], "Usar auto-fit o una clase con regla mobile (p. ej. .inline-form-grid)"


def test_panel_loads_table_fit():
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "js/table-fit.js" in base
