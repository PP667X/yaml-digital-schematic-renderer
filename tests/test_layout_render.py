from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from PIL import Image

from schematic_renderer.model import load_schematic
from schematic_renderer.render import _RasterDraw, render_schematic
from schematic_renderer.layout import make_layout
from schematic_renderer.model import parse_schematic
from schematic_renderer.errors import SchematicError


def test_simple_example_renders_png(tmp_path: Path):
    out = tmp_path / "simple.png"
    render_schematic(load_schematic("examples/simple.yaml"), out)
    image = Image.open(out)
    assert image.size[0] > 300
    assert image.size[1] > 200
    assert image.getbbox() is not None


def test_long_pin_names_fit_side_columns():
    model = parse_schematic({"blocks": {"R": {"symbol": "D", "inputs": ["SYNC_IN"],
                                              "outputs": ["RANGE_ERR"]}}})
    layout = make_layout(model)
    placed = layout.blocks["R"]
    for pin in placed.block.pins:
        width = layout.small_font.getbbox(pin.label)[2]
        space = (placed.inner_rect.left - placed.rect.left if pin.side == "left"
                 else placed.rect.right - placed.inner_rect.right)
        assert space >= width + 16


def test_auto_canvas_includes_wire_detours_without_shrinking_blocks():
    raw = {"canvas": {"layout": "absolute", "scale": 1},
           "blocks": {"A": {"position": [80, 80], "outputs": ["Q"]},
                      "B": {"position": [400, 80], "inputs": ["D"]}}}
    original = make_layout(parse_schematic(raw))
    raw["connections"] = [{"from": "A.Q", "to": "B.D", "points": [
        [300, 96], [300, 900], [2048, 900], [2048, 1000], [360, 1000], [360, 96]]}]
    extended = make_layout(parse_schematic(raw))
    assert extended.width == 2048 + extended.canvas.margin
    assert extended.height == 1000 + extended.canvas.margin
    assert extended.blocks["A"].rect == original.blocks["A"].rect
    assert extended.canvas.font_size == original.canvas.font_size
    raw["canvas"].update(width=800, height=800)
    with pytest.raises(SchematicError, match="exceeds fixed canvas"):
        make_layout(parse_schematic(raw))


def test_png_and_svg_use_the_same_requested_export_scale(tmp_path):
    model = parse_schematic({"canvas": {"scale": 2},
                             "blocks": {"D1": {"symbol": "D", "inputs": ["D"], "outputs": ["Q"]}}})
    layout = make_layout(model)
    png, svg = tmp_path / "scaled.png", tmp_path / "scaled.svg"
    render_schematic(model, png)
    render_schematic(model, svg)
    expected = (layout.width * 2, layout.height * 2)
    with Image.open(png) as image:
        assert image.size == expected
    root = ET.parse(svg).getroot()
    assert (int(root.attrib["width"]), int(root.attrib["height"])) == expected


@pytest.mark.parametrize("width", [1, 2, 3, 4])
@pytest.mark.parametrize("points", [[(8, 20), (52, 20)], [(20, 8), (20, 52)]])
def test_orthogonal_raster_strokes_do_not_depend_on_direction(width, points):
    forward = Image.new("L", (64, 64), 255)
    backward = Image.new("L", (64, 64), 255)
    _RasterDraw(forward).line(points, fill=0, width=width)
    _RasterDraw(backward).line(list(reversed(points)), fill=0, width=width)
    assert forward.tobytes() == backward.tobytes()


@pytest.mark.parametrize("width", [1, 2, 3, 4])
@pytest.mark.parametrize("reverse", [False, True])
def test_pin_and_wire_have_identical_pixel_rows_at_join(tmp_path, width, reverse):
    raw = {"canvas": {"layout": "absolute", "wiring": "connected", "scale": 1, "line_width": width},
           "blocks": {
               "A": {"position": [600 if reverse else 100, 100],
                     "outputs": [{"name": "Q", "side": "left" if reverse else "right"}]},
               "B": {"position": [100 if reverse else 600, 100],
                     "inputs": [{"name": "D", "side": "right" if reverse else "left"}]}}}
    layout = make_layout(parse_schematic(raw))
    sx, y = layout.blocks["A"].pin_points["Q"]
    tx, _ = layout.blocks["B"].pin_points["D"]
    direction = -1 if reverse else 1
    length = layout.canvas.pin_length
    raw["connections"] = [{"from": "A.Q", "to": "B.D",
                           "points": [[sx + direction * length, y], [tx - direction * length, y]]}]
    output = tmp_path / "joined.png"
    render_schematic(parse_schematic(raw), output)
    with Image.open(output) as image:
        samples = [sx + direction * 8, sx + direction * (length + 8),
                   (sx + tx) // 2, tx - direction * 8]
        rows = [tuple(row for row in range(y - 5, y + 6) if image.getpixel((x, row)) == 0)
                for x in samples]
        assert all(row == rows[0] for row in rows)
        assert len(rows[0]) == width
