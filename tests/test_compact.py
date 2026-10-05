from copy import deepcopy

from schematic_renderer.compact import compact_connected
from schematic_renderer.connected import connected_routes, crossings_and_junctions
from schematic_renderer.layout import make_layout
from schematic_renderer.model import parse_schematic
from schematic_renderer.nets import named_nets


def sparse_diagram():
    return {
        "canvas": {"layout": "absolute", "wiring": "connected", "scale": 1,
                   "font_size": 24, "small_font_size": 20},
        "blocks": {
            "A": {"position": [120, 120], "outputs": ["Q"]},
            "C": {"position": [120, 1900], "outputs": ["Q"]},
            "B": {"position": [1400, 900], "inputs": ["A", "B"], "outputs": ["Q"]},
        },
        "connections": [
            {"from": "A.Q", "to": "B.A", "points": [[600, 136], [600, 916]]},
            {"from": "C.Q", "to": "B.B", "points": [[900, 1916], [900, 940]]},
        ],
    }


def test_compaction_removes_slack_but_preserves_symbols_and_connections():
    raw = sparse_diagram()
    saved = deepcopy(raw)
    before_model = parse_schematic(raw)
    before = make_layout(before_model)
    _, original_segments = connected_routes(before_model, before)
    compacted = compact_connected(raw)
    assert raw == saved
    after_model = parse_schematic(compacted)
    after = make_layout(after_model)
    routes, segments = connected_routes(after_model, after)
    assert len(routes) == 2
    assert named_nets(before_model) == named_nets(after_model)
    assert after.width * after.height < before.width * before.height / 2
    for bid, block in before.blocks.items():
        new = after.blocks[bid]
        assert (new.rect.w, new.rect.h) == (block.rect.w, block.rect.h)
        for pin, (x, y) in block.pin_points.items():
            nx, ny = new.pin_points[pin]
            assert (nx - new.rect.x, ny - new.rect.y) == (x - block.rect.x, y - block.rect.y)
    assert after.canvas.font_size == before.canvas.font_size == 24
    assert crossings_and_junctions(segments)[0] == crossings_and_junctions(original_segments)[0] == set()
    assert compacted == compact_connected(raw)


def test_compaction_keeps_branch_junctions():
    raw = sparse_diagram()
    raw["connections"][1] = {
        "from": "A.Q", "to": "B.B", "points": [[600, 136], [600, 940]]}
    model = parse_schematic(compact_connected(raw))
    _, segments = connected_routes(model, make_layout(model))
    crossings, junctions = crossings_and_junctions(segments)
    assert not crossings
    assert junctions
