import xml.etree.ElementTree as ET

import pytest

from schematic_renderer.connected import connected_routes, crossings_and_junctions
from schematic_renderer.errors import SchematicError
from schematic_renderer.layout import make_layout
from schematic_renderer.model import parse_schematic
from schematic_renderer.render import render_schematic


def crossing_document():
    raw = {"canvas": {"layout": "absolute", "wiring": "connected", "scale": 1},
           "blocks": {"A": {"position": [80, 80], "outputs": ["Q"]},
                      "B": {"position": [80, 280], "outputs": ["Q"]},
                      "C": {"position": [600, 120], "inputs": ["D"]},
                      "D": {"position": [600, 320], "inputs": ["D"]}},
           "connections": []}
    layout = make_layout(parse_schematic(raw))
    ya = layout.blocks["A"].pin_points["Q"][1]
    yb = layout.blocks["B"].pin_points["Q"][1]
    yc = layout.blocks["C"].pin_points["D"][1]
    yd = layout.blocks["D"].pin_points["D"][1]
    raw["connections"] = [
        {"from": "A.Q", "to": "D.D", "points": [[330, ya], [330, yd]]},
        {"from": "B.Q", "to": "C.D", "points": [[430, yb], [430, yc]]}]
    return raw


def test_continuous_routes_have_crossovers_and_export_svg(tmp_path):
    schematic = parse_schematic(crossing_document())
    routes, segments = connected_routes(schematic, make_layout(schematic))
    crosses, junctions = crossings_and_junctions(segments)
    assert len(routes) == 2
    assert len(crosses) == 1
    assert not junctions
    out = tmp_path / "connected.svg"
    render_schematic(schematic, out)
    root = ET.parse(out).getroot()
    assert len(root.findall("{http://www.w3.org/2000/svg}path")) == 1


def test_junction_is_not_a_crossing():
    crosses, junctions = crossings_and_junctions([
        ((0, 10), (30, 10), "N"), ((10, 10), (10, 30), "N")])
    assert not crosses
    assert junctions == {(10, 10)}


def test_connected_rejects_collinear_different_nets():
    raw = crossing_document()
    raw["connections"][1]["points"] = [[330, 296], [330, 136]]
    schematic = parse_schematic(raw)
    with pytest.raises(SchematicError, match="Overlapping"):
        connected_routes(schematic, make_layout(schematic))


def test_connected_rejects_missing_route():
    raw = crossing_document()
    raw["connections"][0].pop("points")
    schematic = parse_schematic(raw)
    with pytest.raises(SchematicError, match="prepared"):
        connected_routes(schematic, make_layout(schematic))


def test_connected_rejects_wire_through_block_in_another_spatial_bin():
    raw = crossing_document()
    raw["blocks"]["OBSTACLE"] = {"position": [300, 80], "inputs": ["A"]}
    schematic = parse_schematic(raw)
    with pytest.raises(SchematicError, match="passes through OBSTACLE"):
        connected_routes(schematic, make_layout(schematic))
