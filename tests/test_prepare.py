import json
from types import SimpleNamespace

import pytest

from schematic_renderer import prepare
from schematic_renderer.model import parse_schematic
from schematic_renderer.layout import make_layout


@pytest.mark.parametrize("canvas", ["missing", None, {}])
def test_prepare_accepts_omitted_or_empty_canvas(monkeypatch, canvas):
    raw = {"blocks": {"A": {"outputs": ["Q"]}}}
    if canvas != "missing":
        raw["canvas"] = canvas
    monkeypatch.setattr(prepare.shutil, "which", lambda _: "node")
    result = {"children": [{"id": "A", "x": 0, "y": 0}], "edges": []}
    monkeypatch.setattr(prepare.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps(result)))
    prepared = prepare.prepare_connected(raw)
    assert prepared["canvas"]["wiring"] == "connected"
    assert prepared["canvas"]["layout"] == "absolute"
    assert make_layout(parse_schematic(prepared)).width > 0
