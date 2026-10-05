"""Bake ELK's placement and continuous orthogonal routes into ordinary YAML."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw
import yaml

from .errors import SchematicError
from .layout import Rect, _font, _measure_block, _pin_positions
from .model import parse_schematic


def prepare_connected(raw: dict, *, strategy: str | None = None, compact: bool = True) -> dict:
    result = deepcopy(raw)
    schematic = parse_schematic(raw)
    if schematic.ports:
        raise SchematicError("ELK preparation currently requires blocks, including I/O blocks.")
    c = schematic.canvas
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font, small = _font(c.font_size), _font(c.small_font_size)
    children = []
    for block in schematic.blocks.values():
        w, h = _measure_block(block, c, font, small, draw)
        rect = Rect(c.pin_length, 30, w, h)
        points, _ = _pin_positions(block.pins, rect, c)
        ports = []
        for pin in block.pins:
            x, y = points[pin.name]
            x += -c.pin_length if pin.side == "left" else c.pin_length
            if pin.side not in {"left", "right"}:
                raise SchematicError("ELK preparation requires left/right pins.")
            ports.append({"id": f"{block.id}.{pin.name}", "x": x, "y": y,
                          "width": 0, "height": 0,
                          "layoutOptions": {"elk.port.side": "WEST" if pin.side == "left" else "EAST"}})
        options = {"elk.portConstraints": "FIXED_POS"}
        if block.id.startswith(("RA", "RB")) or block.id == "RSYNC":
            options["elk.layered.layering.layerConstraint"] = "FIRST"
        if block.id == "CLOCK":
            options["elk.layered.layering.layerConstraint"] = "FIRST_SEPARATE"
        if block.id.startswith("RY") or block.id in {"YSYNC", "RERR"}:
            options["elk.layered.layering.layerConstraint"] = "LAST"
        children.append({"id": block.id, "width": w + 2 * c.pin_length,
                         "height": h + 30, "ports": ports, "layoutOptions": options})
    edges, connections = [], []
    for connection in schematic.connections:
        source = connection.chain[0]
        for target in connection.chain[1:]:
            edge_id = f"e{len(edges)}"
            edges.append({"id": edge_id, "sources": [source], "targets": [target]})
            connections.append((source, target))
    graph = {"id": "root", "children": children, "edges": edges, "layoutOptions": {
        "elk.algorithm": "layered", "elk.direction": "RIGHT", "elk.edgeRouting": "ORTHOGONAL",
        "elk.spacing.nodeNode": 36, "elk.spacing.edgeNode": 16, "elk.spacing.edgeEdge": 12,
        "elk.layered.spacing.nodeNodeBetweenLayers": 56,
        "elk.layered.spacing.edgeEdgeBetweenLayers": 12,
        "elk.layered.spacing.edgeNodeBetweenLayers": 16,
        "elk.layered.mergeEdges": True, "elk.randomSeed": 1,
        "elk.layered.nodePlacement.strategy": strategy or ("SIMPLE" if raw.get("layout_groups") else "LINEAR_SEGMENTS"),
        "elk.layered.nodePlacement.favorStraightEdges": False,
        "elk.json.edgeCoords": "ROOT",
    }}
    groups = raw.get("layout_groups", {})
    if groups:
        remaining = {child["id"]: child for child in children}
        compound = []
        for name, members in groups.items():
            if any(bid not in remaining for bid in members):
                raise SchematicError(f"Invalid or duplicate member in layout group {name}.")
            options = dict(graph["layoutOptions"])
            options.update({"elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
                            "elk.padding": "[top=12,left=12,bottom=12,right=12]"})
            compound.append({"id": f"cell_{name}", "children": [remaining.pop(bid) for bid in members],
                             "layoutOptions": options})
        graph["children"] = list(remaining.values()) + compound
        graph["layoutOptions"]["elk.hierarchyHandling"] = "INCLUDE_CHILDREN"
    node = shutil.which("node")
    if node is None:
        try:
            import nodejs_wheel
            node = str(Path(nodejs_wheel.__file__).parent / "node.exe")
            if not Path(node).exists():
                node = str(Path(nodejs_wheel.__file__).parent / "bin" / "node")
        except ImportError as exc:
            raise SchematicError("Install Node.js or pip install nodejs-wheel for ELK layout.") from exc
    try:
        process = subprocess.run([node, str(Path(__file__).with_name("elk_layout.cjs"))],
                                 input=json.dumps(graph), text=True, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired as exc:
        raise SchematicError("ELK layout exceeded 180 seconds.") from exc
    if process.returncode:
        raise SchematicError(f"ELK layout failed (run npm install first): {process.stderr[-1500:]}")
    placed = json.loads(process.stdout)
    margin = max(80, c.margin)
    def position_children(parent, origin_x=0, origin_y=0):
        for child in parent.get("children", []):
            x, y = origin_x + child["x"], origin_y + child["y"]
            if child.get("children"):
                position_children(child, x, y)
            else:
                result["blocks"][child["id"]]["position"] = [round(x) + margin + c.pin_length,
                                                             round(y) + margin + 30]
    position_children(placed)
    result["connections"] = []
    by_id = {edge["id"]: edge for edge in placed["edges"]}
    for index, (source, target) in enumerate(connections):
        edge = by_id[f"e{index}"]
        sections = edge.get("sections", [])
        if len(sections) != 1:
            raise SchematicError(f"Expected one complete route for {source} -> {target}.")
        section = sections[0]
        points = [section["startPoint"], *section.get("bendPoints", []), section["endPoint"]]
        result["connections"].append({"from": source, "to": target,
            "points": [[round(p["x"]) + margin, round(p["y"]) + margin] for p in points]})
    result["canvas"] = {**(result.get("canvas") or {}), "layout": "absolute", "wiring": "connected"}
    # Prepared diagrams grow to their contents; do not impose a target page size.
    result["canvas"].pop("width", None)
    result["canvas"].pop("height", None)
    result.pop("primitives", None)
    if compact:
        from .compact import compact_connected
        result = compact_connected(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Place and route every YAML connection with ELK.")
    parser.add_argument("input")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()
    raw = yaml.safe_load(Path(args.input).read_text(encoding="utf-8"))
    Path(args.output).write_text(yaml.safe_dump(prepare_connected(raw), sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    main()
