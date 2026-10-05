"""Validate explicit geometry and distinguish junctions from wire crossings."""
from __future__ import annotations

from collections import defaultdict

from .errors import SchematicError
from .layout import endpoint_point
from .nets import named_nets
from .router import RoutedConnection, _allowed_rect_touch, _overlap, _segment_rect


def connected_routes(schematic, layout):
    names = named_nets(schematic)
    routes = []
    segments = []
    block_bins = defaultdict(list)
    for block in layout.blocks.values():
        for column in range(block.rect.left // 256, block.rect.right // 256 + 1):
            block_bins[column].append(block)
    for connection in schematic.connections:
        if len(connection.chain) != 2 or not connection.points:
            raise SchematicError("Connected wiring requires prepared point routes for every pair.")
        points = [endpoint_point(connection.chain[0], layout), *connection.points,
                  endpoint_point(connection.chain[1], layout)]
        points = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]
        net = names[connection.chain[0]]
        pairs = list(zip(points, points[1:]))
        for a, b in pairs:
            if a[0] != b[0] and a[1] != b[1]:
                raise SchematicError(f"Diagonal route in {connection.chain}.")
            if not all(0 <= x <= layout.width and 0 <= y <= layout.height for x, y in (a, b)):
                raise SchematicError(f"Route exceeds canvas: {connection.chain}.")
            segment_rect = _segment_rect(a, b)
            candidates = {}
            for column in range(segment_rect.left // 256, segment_rect.right // 256 + 1):
                for block in block_bins[column]:
                    candidates[block.block.id] = block
            for block in candidates.values():
                rect = block.rect
                if segment_rect.intersects(rect) and not _allowed_rect_touch(a, b, rect):
                    raise SchematicError(f"Wire {connection.chain} passes through {block.block.id}.")
            segments.append((a, b, net))
        routes.append(RoutedConnection(connection, tuple(pairs), tuple(points)))
    # Different nets must never share even a short collinear interval.
    tracks = defaultdict(list)
    for a, b, net in segments:
        key = ("H", a[1]) if a[1] == b[1] else ("V", a[0])
        for c, d, other in tracks[key]:
            if other != net and _overlap(a, b, c, d):
                raise SchematicError(f"Overlapping nets {net} / {other} at {a}.")
        tracks[key].append((a, b, net))
    return tuple(routes), segments


def crossings_and_junctions(segments):
    horizontal = defaultdict(list)
    vertical = defaultdict(list)
    endpoints = defaultdict(set)
    for a, b, net in segments:
        if a[1] == b[1]:
            horizontal[a[1]].append((min(a[0], b[0]), max(a[0], b[0]), net))
        else:
            vertical[a[0]].append((min(a[1], b[1]), max(a[1], b[1]), net))
        endpoints[net].update((a, b))
    crossings = set()
    junctions = set()
    for x, columns in vertical.items():
        for low_y, high_y, vnet in columns:
            for y, rows in horizontal.items():
                if not low_y <= y <= high_y:
                    continue
                for low_x, high_x, hnet in rows:
                    if not low_x <= x <= high_x:
                        continue
                    if vnet != hnet:
                        crossings.add((x, y))
                    elif low_y < y < high_y or low_x < x < high_x:
                        junctions.add((x, y))
    return crossings, junctions


def draw_connected(draw, routes, segments, layout):
    width = layout.canvas.line_width
    for route in routes:
        for a, b in route.segments:
            draw.line([a, b], fill="black", width=width)
    crossings, junctions = crossings_and_junctions(segments)
    for x, y in sorted(crossings):
        # Lift the vertical wire over the horizontal one. No junction dot here.
        draw.line([(x, y - 5), (x, y + 5)], fill="white", width=width + 4)
        draw.line([(x - 5, y), (x + 5, y)], fill="black", width=width)
        draw.arc((x - 5, y - 5, x + 5, y + 5), 270, 90, fill="black", width=width)
    for x, y in sorted(junctions):
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill="black")
