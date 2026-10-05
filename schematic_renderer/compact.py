"""Compact routed drawings using separation constraints, without scaling symbols."""
from __future__ import annotations

import argparse
from copy import deepcopy
import heapq
from pathlib import Path

import yaml

from .layout import endpoint_point, make_layout
from .model import parse_schematic
from .nets import named_nets


class _Coordinates:
    """Weighted disjoint sets represent rigid blocks and straight wire sections."""
    def __init__(self):
        self.parent = []
        self.offset = []

    def add(self):
        index = len(self.parent)
        self.parent.append(index)
        self.offset.append(0)
        return index, 0

    def resolve(self, expression):
        index, offset = expression
        root = index
        total = 0
        while self.parent[root] != root:
            total += self.offset[root]
            root = self.parent[root]
        distance = total
        while self.parent[index] != index:
            parent, step = self.parent[index], self.offset[index]
            self.parent[index], self.offset[index] = root, total
            total -= step
            index = parent
        return root, distance + offset

    def join(self, a, b):
        ra, da = self.resolve(a)
        rb, db = self.resolve(b)
        if ra == rb:
            if da != db:
                raise ValueError("Inconsistent rigid coordinates in prepared routes.")
        else:
            self.parent[ra], self.offset[ra] = rb, db - da


def compact_connected(raw: dict) -> dict:
    """Preserve route topology and dimensions; remove slack on both axes."""
    result = deepcopy(raw)
    if result["canvas"].get("wiring") != "connected":
        raise ValueError("Compaction requires prepared connected wiring.")
    for axis in (1, 0):
        _compact_axis(result, axis)
    result["canvas"].pop("width", None)
    result["canvas"].pop("height", None)
    return result


def _compact_axis(raw, axis):
    schematic = parse_schematic(raw)
    layout = make_layout(schematic)
    names = named_nets(schematic)
    coordinates = _Coordinates()
    bases = {bid: coordinates.add() for bid in layout.blocks}
    features = []
    paths = []
    shared = {}

    def pin_expression(ref):
        owner = ref.split(".")[0]
        block = layout.blocks[owner]
        origin = (block.rect.x, block.rect.y)[axis]
        point = endpoint_point(ref, layout)
        return bases[owner][0], point[axis] - origin

    for connection in schematic.connections:
        start, end = connection.chain
        points = [endpoint_point(start, layout), *connection.points, endpoint_point(end, layout)]
        expressions = [pin_expression(start), *[coordinates.add() for _ in connection.points], pin_expression(end)]
        paths.append(expressions)
        net = names[start]
        for a, b, ea, eb in zip(points, points[1:], expressions, expressions[1:]):
            if a[axis] == b[axis]:
                coordinates.join(ea, eb)
                key = net, a[axis]
                if key in shared:
                    coordinates.join(ea, shared[key])
                else:
                    shared[key] = ea
                low, high = sorted((a[1-axis], b[1-axis]))
                features.append((low - 6, high + 6, a[axis], ea))
            else:
                for p, expr in ((a, ea), (b, eb)):
                    features.append((p[1-axis] - 6, p[1-axis] + 6, p[axis], expr))

    columns = {}
    for bid, placed in layout.blocks.items():
        r = placed.rect
        if axis == 0:
            # Register banks remain aligned; internal gates can use local gaps.
            bank = ("input" if bid.startswith(("RA", "RB")) or bid == "RSYNC" else
                    "output" if bid.startswith("RY") or bid in {"YSYNC", "RERR"} else None)
            if bank is not None:
                key = bank, r.x
                if key in columns:
                    coordinates.join(bases[bid], columns[key])
                else:
                    columns[key] = bases[bid]
            low, high, offsets, origin = r.top - 28, r.bottom + 8, (-8, r.w + 8), r.x
        else:
            low, high, offsets, origin = r.left - 8, r.right + 8, (-28, r.h + 8), r.y
        for offset in offsets:
            features.append((low, high, origin + offset, (bases[bid][0], offset)))

    features = [(lo, hi, old, *coordinates.resolve(expr)) for lo, hi, old, expr in features]
    roots = {root for _, _, _, root, _ in features}
    original = {}
    for _, _, old, root, offset in features:
        value = old - offset
        if root in original and original[root] != value:
            raise ValueError("Compaction coordinates disagree with the original drawing.")
        original[root] = value
    bounds = {root: -10**9 for root in roots}
    edges = {root: {} for root in roots}
    margin = max(80, layout.canvas.margin)
    active = []
    for feature in sorted(set(features)):
        lo, hi, old, root, offset = feature
        bounds[root] = max(bounds[root], margin - offset)
        active = [other for other in active if other[1] >= lo]
        for other in active:
            if root == other[3]:
                continue
            first, second = (other, feature) if other[2] <= old else (feature, other)
            # Retain the order of overlapping projections and protect wire jumps.
            gap = min(12, second[2] - first[2])
            weight = first[4] - second[4] + gap
            source, target = first[3], second[3]
            edges[source][target] = max(edges[source].get(target, -10**9), weight)
        active.append(feature)

    # Reweight separation constraints by the feasible original positions.
    # Their slack is nonnegative, so Dijkstra finds maximal legal translations.
    shifts = {root: original[root] - bounds[root] for root in roots}
    queue = [(shift, root) for root, shift in shifts.items()]
    heapq.heapify(queue)
    while queue:
        shift, source = heapq.heappop(queue)
        if shift != shifts[source]:
            continue
        for target, gap in edges[source].items():
            slack = original[target] - original[source] - gap
            if slack < 0:
                raise ValueError("Original drawing violates a separation constraint.")
            candidate = shift + slack
            if candidate < shifts[target]:
                shifts[target] = candidate
                heapq.heappush(queue, (candidate, target))
    bounds = {root: original[root] - shifts[root] for root in roots}

    def value(expr):
        root, offset = coordinates.resolve(expr)
        return bounds[root] + offset

    for bid, base in bases.items():
        raw["blocks"][bid]["position"][axis] = value(base)
    for connection, expressions in zip(raw["connections"], paths):
        for point, expression in zip(connection["points"], expressions[1:-1]):
            point[axis] = value(expression)


def main():
    parser = argparse.ArgumentParser(description="Compact prepared routes without shrinking blocks.")
    parser.add_argument("input")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()
    raw = yaml.safe_load(Path(args.input).read_text(encoding="utf-8"))
    result = compact_connected(raw)
    Path(args.output).write_text(yaml.safe_dump(result, sort_keys=False), encoding="utf-8")
    before, after = make_layout(parse_schematic(raw)), make_layout(parse_schematic(result))
    print(f"{before.width} x {before.height} -> {after.width} x {after.height}")


if __name__ == "__main__":
    main()
