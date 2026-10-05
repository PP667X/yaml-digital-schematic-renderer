from __future__ import annotations

from dataclasses import dataclass
import heapq

from .errors import SchematicError
from .layout import Layout, Rect, endpoint_point, endpoint_side
from .model import Connection


@dataclass(frozen=True)
class RoutedConnection:
    connection: Connection
    segments: tuple[tuple[tuple[int, int], tuple[int, int]], ...]
    points: tuple[tuple[int, int], ...]


def route_connections(connections: tuple[Connection, ...], layout: Layout) -> tuple[RoutedConnection, ...]:
    routed: list[RoutedConnection] = []
    occupied_segments: list[tuple[tuple[int, int], tuple[int, int], str]] = []
    pairs = []
    order = 0
    for connection in connections:
        net = connection.chain[0]
        for left, right in zip(connection.chain, connection.chain[1:]):
            start = endpoint_point(left, layout)
            end = endpoint_point(right, layout)
            pairs.append((connection, net, left, right, order, _route_priority(start, end, bool(connection.points))))
            order += 1
    for connection, net, left, right, _, _ in sorted(pairs, key=lambda item: (item[5], item[4])):
        points = _route_pair(left, right, connection.points, layout, occupied_segments, net)
        segments = tuple(zip(points, points[1:]))
        _check_segments(left, right, segments, occupied_segments, layout, net)
        routed.append(RoutedConnection(connection, segments, tuple(points)))
        occupied_segments.extend((a, b, net) for a, b in segments)
    return tuple(routed)


def _route_priority(start: tuple[int, int], end: tuple[int, int], manual: bool) -> tuple[int, int, int]:
    vertical = abs(start[1] - end[1])
    horizontal = abs(start[0] - end[0])
    return (1 if manual else 0, vertical, horizontal)


def _route_pair(left: str, right: str, manual: tuple[tuple[int, int], ...], layout: Layout, occupied_segments, net: str) -> list[tuple[int, int]]:
    start = endpoint_point(left, layout)
    end = endpoint_point(right, layout)
    if manual:
        return _orthogonalize([start, *manual, end])
    direct = _try_simple(start, end, layout, occupied_segments, net)
    if direct:
        return direct
    path = _grid_route(start, end, layout, occupied_segments, net)
    if not path:
        raise SchematicError(f"Cannot route {left} -> {right}; add explicit points.")
    return path


def _stub(point: tuple[int, int], side: str, length: int) -> tuple[int, int]:
    x, y = point
    return {
        "left": (x - length, y),
        "right": (x + length, y),
        "top": (x, y - length),
        "bottom": (x, y + length),
    }[side]


def _try_simple(start: tuple[int, int], end: tuple[int, int], layout: Layout, occupied_segments, net: str) -> list[tuple[int, int]] | None:
    candidates = [
        [start, end],
        [start, (end[0], start[1]), end],
        [start, (start[0], end[1]), end],
    ]
    mid_x = (start[0] + end[0]) // 2
    mid_y = (start[1] + end[1]) // 2
    candidates.extend([
        [start, (mid_x, start[1]), (mid_x, end[1]), end],
        [start, (start[0], mid_y), (end[0], mid_y), end],
    ])
    for points in candidates:
        ortho = _orthogonalize(points)
        if _path_clear(ortho, layout, occupied_segments, net):
            return ortho
    return None


def _grid_route(start: tuple[int, int], end: tuple[int, int], layout: Layout, occupied_segments, net: str) -> list[tuple[int, int]] | None:
    step = layout.canvas.route_step
    max_x = _ceil(layout.width + layout.canvas.margin, step)
    max_y = _ceil(layout.height + layout.canvas.margin, step)
    xs = sorted(set(range(0, max_x + step, step)) | _nearby_channels(start[0], end[0], max_x, step))
    ys = sorted(set(range(0, max_y + step, step)) | _nearby_channels(start[1], end[1], max_y, step))
    x_index = {x: idx for idx, x in enumerate(xs)}
    y_index = {y: idx for idx, y in enumerate(ys)}
    start_state = (start, "")
    heap: list[tuple[int, int, int, tuple[int, int], str]] = [(0, 0, 0, start, "")]
    best: dict[tuple[tuple[int, int], str], int] = {start_state: 0}
    prev: dict[tuple[tuple[int, int], str], tuple[tuple[int, int], str] | None] = {start_state: None}
    serial = 1
    end_state: tuple[tuple[int, int], str] | None = None
    while heap:
        _, cost, _, node, direction = heapq.heappop(heap)
        state = (node, direction)
        if cost != best.get(state):
            continue
        if node == end:
            end_state = state
            break
        for nxt, next_direction in _neighbors(node, xs, ys, x_index, y_index):
            if nxt not in {start, end} and any(rect.contains_point(nxt) for rect in layout.occupied):
                continue
            if not _segment_clear(node, nxt, layout):
                continue
            if _segment_conflicts_existing(node, nxt, occupied_segments, {start, end}, net):
                continue
            extra = _edge_cost(node, nxt, direction, next_direction, start, end)
            next_state = (nxt, next_direction)
            new_cost = cost + extra
            if new_cost < best.get(next_state, 10**12):
                best[next_state] = new_cost
                prev[next_state] = state
                heapq.heappush(heap, (new_cost + _manhattan(nxt, end), new_cost, serial, nxt, next_direction))
                serial += 1
    if end_state:
        path = _reconstruct(prev, end_state)
        compact = _orthogonalize(path)
        if _path_clear(compact, layout, occupied_segments, net):
            return compact
    return None


def _orthogonalize(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for point in points:
        if out and out[-1] == point:
            continue
        if out and out[-1][0] != point[0] and out[-1][1] != point[1]:
            out.append((point[0], out[-1][1]))
        out.append(point)
    compact: list[tuple[int, int]] = []
    for point in out:
        if len(compact) >= 2:
            a, b = compact[-2], compact[-1]
            if (a[0] == b[0] == point[0]) or (a[1] == b[1] == point[1]):
                compact[-1] = point
                continue
        compact.append(point)
    return compact


def _path_clear(points: list[tuple[int, int]], layout: Layout, occupied_segments, net: str) -> bool:
    return all(
        _segment_clear(a, b, layout) and not _segment_conflicts_existing(a, b, occupied_segments, {points[0], points[-1]}, net)
        for a, b in zip(points, points[1:])
    )


def _segment_clear(a: tuple[int, int], b: tuple[int, int], layout: Layout) -> bool:
    if a[0] != b[0] and a[1] != b[1]:
        return False
    seg_rect = _segment_rect(a, b).inflate(3)
    for rect in layout.occupied:
        # Endpoints may touch their own block or port; only reject real pass-throughs.
        if seg_rect.intersects(rect) and not _allowed_rect_touch(a, b, rect):
            return False
    return True


def _check_segments(name_a: str, name_b: str, segments, occupied_segments, layout: Layout, net: str) -> None:
    for a, b in segments:
        if a[0] != b[0] and a[1] != b[1]:
            raise SchematicError(f"Non-orthogonal segment in {name_a} -> {name_b}.")
        for rect in layout.occupied:
            if _segment_rect(a, b).inflate(1).intersects(rect) and not _allowed_rect_touch(a, b, rect):
                raise SchematicError(f"Wire {name_a} -> {name_b} passes through occupied content.")
        if _segment_conflicts_existing(a, b, occupied_segments, {a, b}, net):
            raise SchematicError(f"Wire {name_a} -> {name_b} intersects or overlaps another wire; add manual points.")


def _segment_rect(a: tuple[int, int], b: tuple[int, int]) -> Rect:
    x1, y1 = a
    x2, y2 = b
    return Rect(min(x1, x2), min(y1, y2), abs(x2 - x1) or 1, abs(y2 - y1) or 1)


def _allowed_rect_touch(a: tuple[int, int], b: tuple[int, int], rect: Rect) -> bool:
    a_inside = rect.contains_point(a)
    b_inside = rect.contains_point(b)
    if not (a_inside or b_inside):
        return False
    if a_inside and b_inside:
        return False
    point = a if a_inside else b
    other = b if a_inside else a
    if point[0] == rect.left and other[1] == point[1] and other[0] <= rect.left:
        return True
    if point[0] == rect.right and other[1] == point[1] and other[0] >= rect.right:
        return True
    if point[1] == rect.top and other[0] == point[0] and other[1] <= rect.top:
        return True
    if point[1] == rect.bottom and other[0] == point[0] and other[1] >= rect.bottom:
        return True
    return False


def _overlap(a, b, c, d) -> bool:
    if a[0] == b[0] == c[0] == d[0]:
        r1 = sorted([a[1], b[1]])
        r2 = sorted([c[1], d[1]])
        return max(r1[0], r2[0]) < min(r1[1], r2[1])
    if a[1] == b[1] == c[1] == d[1]:
        r1 = sorted([a[0], b[0]])
        r2 = sorted([c[0], d[0]])
        return max(r1[0], r2[0]) < min(r1[1], r2[1])
    return False


def _neighbors(
    node: tuple[int, int],
    xs: list[int],
    ys: list[int],
    x_index: dict[int, int],
    y_index: dict[int, int],
) -> list[tuple[tuple[int, int], str]]:
    x, y = node
    out: list[tuple[tuple[int, int], str]] = []
    xi = x_index[x]
    yi = y_index[y]
    if xi + 1 < len(xs):
        out.append(((xs[xi + 1], y), "R"))
    if yi + 1 < len(ys):
        out.append(((x, ys[yi + 1]), "D"))
    if yi - 1 >= 0:
        out.append(((x, ys[yi - 1]), "U"))
    if xi - 1 >= 0:
        out.append(((xs[xi - 1], y), "L"))
    return out


def _edge_cost(a: tuple[int, int], b: tuple[int, int], direction: str, next_direction: str, start: tuple[int, int], end: tuple[int, int]) -> int:
    cost = _manhattan(a, b)
    if direction and direction != next_direction:
        cost += 80
    if next_direction == "L":
        cost += 140
    if next_direction in {"U", "D"}:
        cost += 12
        if start[0] < end[0]:
            cost += max(0, b[0] - start[0]) // 2
        elif start[0] > end[0]:
            cost += max(0, start[0] - b[0]) // 2
    return cost


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _ceil(value: int, step: int) -> int:
    return ((value + step - 1) // step) * step


def _nearby_channels(a: int, b: int, upper: int, step: int) -> set[int]:
    half = max(2, step // 2)
    quarter = max(2, step // 4)
    values: set[int] = set()
    for value in (a, b):
        for candidate in (value - step, value - half, value - quarter, value, value + quarter, value + half, value + step):
            if 0 <= candidate <= upper:
                values.add(candidate)
    return values


def _segment_conflicts_existing(
    a: tuple[int, int],
    b: tuple[int, int],
    occupied_segments,
    allowed_touch_points: set[tuple[int, int]],
    net: str,
) -> bool:
    for c, d, other_net in occupied_segments:
        if other_net == net:
            continue
        if _segments_conflict(a, b, c, d, allowed_touch_points) or _same_track(a, b, c, d):
            return True
    return False


def _segments_conflict(
    a: tuple[int, int],
    b: tuple[int, int],
    c: tuple[int, int],
    d: tuple[int, int],
    allowed_touch_points: set[tuple[int, int]],
) -> bool:
    if a == b or c == d:
        return False
    if _overlap(a, b, c, d):
        return True
    point = _orthogonal_intersection(a, b, c, d)
    if point is None:
        return False
    return point not in allowed_touch_points


def _same_track(a: tuple[int, int], b: tuple[int, int], c: tuple[int, int], d: tuple[int, int]) -> bool:
    if a[0] == b[0] == c[0] == d[0]:
        return True
    return False


def _orthogonal_intersection(a, b, c, d) -> tuple[int, int] | None:
    if a[1] == b[1] and c[0] == d[0]:
        y = a[1]
        x = c[0]
        if _between(x, a[0], b[0]) and _between(y, c[1], d[1]):
            return (x, y)
    if a[0] == b[0] and c[1] == d[1]:
        x = a[0]
        y = c[1]
        if _between(y, a[1], b[1]) and _between(x, c[0], d[0]):
            return (x, y)
    return None


def _between(value: int, left: int, right: int) -> bool:
    lo, hi = sorted((left, right))
    return lo <= value <= hi


def _reconstruct(
    prev: dict[tuple[tuple[int, int], str], tuple[tuple[int, int], str] | None],
    state: tuple[tuple[int, int], str],
) -> list[tuple[int, int]]:
    path = [state[0]]
    while prev[state] is not None:
        state = prev[state]  # type: ignore[assignment]
        path.append(state[0])
    return list(reversed(path))
