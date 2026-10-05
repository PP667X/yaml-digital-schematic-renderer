from __future__ import annotations

from dataclasses import dataclass
from PIL import Image, ImageDraw, ImageFont

from .errors import SchematicError
from .model import Block, Canvas, Pin, Port, Schematic
from .nets import named_nets


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def left(self) -> int: return self.x
    @property
    def right(self) -> int: return self.x + self.w
    @property
    def top(self) -> int: return self.y
    @property
    def bottom(self) -> int: return self.y + self.h

    def inflate(self, amount: int) -> "Rect":
        return Rect(self.x - amount, self.y - amount, self.w + amount * 2, self.h + amount * 2)

    def intersects(self, other: "Rect") -> bool:
        return not (self.right <= other.left or other.right <= self.left or self.bottom <= other.top or other.bottom <= self.top)

    def contains_point(self, point: tuple[int, int]) -> bool:
        x, y = point
        return self.left <= x <= self.right and self.top <= y <= self.bottom


@dataclass(frozen=True)
class PlacedBlock:
    block: Block
    rect: Rect
    inner_rect: Rect
    pin_points: dict[str, tuple[int, int]]
    pin_label_points: dict[str, tuple[int, int]]


@dataclass(frozen=True)
class PlacedPort:
    port: Port
    rect: Rect
    inner_rect: Rect
    point: tuple[int, int]
    pin_label: str
    bounds: Rect


@dataclass(frozen=True)
class Layout:
    canvas: Canvas
    font: ImageFont.ImageFont
    small_font: ImageFont.ImageFont
    blocks: dict[str, PlacedBlock]
    ports: dict[str, PlacedPort]
    occupied: tuple[Rect, ...]
    width: int
    height: int


def make_layout(schematic: Schematic) -> Layout:
    canvas = schematic.canvas
    font = _font(canvas.font_size)
    small_font = _font(canvas.small_font_size)
    measurer = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    block_sizes = {bid: _measure_block(block, canvas, font, small_font, measurer) for bid, block in schematic.blocks.items()}
    col_widths: dict[int, int] = {}
    row_heights: dict[int, int] = {}
    for block_id, (w, h) in block_sizes.items():
        col, row = schematic.blocks[block_id].position
        col_widths[col] = max(col_widths.get(col, 0), w)
        row_heights[row] = max(row_heights.get(row, 0), h)
    port_size = 92
    for port in schematic.ports.values():
        col, row = port.position
        col_widths[col] = max(col_widths.get(col, 0), port_size)
        row_heights[row] = max(row_heights.get(row, 0), canvas.min_block_height)
    label_space: dict[int, dict[str, int]] = {}
    if canvas.wiring == "named":
        for ref, name in named_nets(schematic).items():
            owner, _, pin = ref.partition(".")
            if owner in schematic.blocks:
                block = schematic.blocks[owner]
                col = block.position[0]
                side = next(p.side for p in block.pins if p.name == pin)
            else:
                port = schematic.ports[owner]
                col = port.position[0]
                side = "right" if port.direction == "input" else "left"
            if side not in {"left", "right"}:
                raise SchematicError("Named wiring requires left/right pins.")
            width = _text_size(measurer, name, small_font)[0] + canvas.pin_length + 12
            spaces = label_space.setdefault(col, {"left": 0, "right": 0})
            spaces[side] = max(spaces[side], width)
    widths = {col: width + sum(label_space.get(col, {}).values()) for col, width in col_widths.items()}
    x_by_col = _axis_positions(widths, canvas.margin, canvas.column_gap)
    x_by_col = {col: x + label_space.get(col, {}).get("left", 0) for col, x in x_by_col.items()}
    y_by_row = _axis_positions(row_heights, canvas.margin + 24, canvas.row_gap)

    blocks: dict[str, PlacedBlock] = {}
    occupied: list[Rect] = []
    for block in schematic.blocks.values():
        w, h = block_sizes[block.id]
        col, row = block.position
        x, y = (col, row) if canvas.layout == "absolute" else (x_by_col[col], y_by_row[row])
        rect = Rect(x + block.offset[0], y + block.offset[1], w, h)
        left_w = max([canvas.pin_length] + [
            _text_size(measurer, pin.label, small_font)[0] + 16
            for pin in block.pins if pin.side == "left"])
        right_w = max([canvas.pin_length] + [
            _text_size(measurer, pin.label, small_font)[0] + 16
            for pin in block.pins if pin.side == "right"])
        inner = Rect(rect.x + left_w, rect.y, rect.w - left_w - right_w, rect.h)
        if any(rect.intersects(other) for other in occupied):
            raise SchematicError(f"Block {block.id} intersects another block.")
        placed = PlacedBlock(block, rect, inner, *_pin_positions(block.pins, rect, canvas))
        blocks[block.id] = placed
        occupied.append(rect)

    ports: dict[str, PlacedPort] = {}
    for port in schematic.ports.values():
        col, row = port.position
        placed = _place_port(port, x_by_col[col] + port.offset[0], y_by_row[row] + port.offset[1], canvas, small_font, measurer)
        ports[port.id] = placed
        occupied.append(placed.bounds)

    min_x, min_y, max_x, max_y = _content_bounds(blocks, ports)
    # Explicit wire channels can extend beyond every block in the diagram.
    for connection in schematic.connections:
        for x, y in connection.points:
            min_x, min_y = min(min_x, x), min(min_y, y)
            max_x, max_y = max(max_x, x), max(max_y, y)
    for placed in blocks.values():
        for pin in placed.block.pins:
            x, y = placed.pin_points[pin.name]
            x += {"left": -canvas.pin_length, "right": canvas.pin_length}.get(pin.side, 0)
            y += {"top": -canvas.pin_length, "bottom": canvas.pin_length}.get(pin.side, 0)
            min_x, min_y = min(min_x, x), min(min_y, y)
            max_x, max_y = max(max_x, x), max(max_y, y)
    if label_space:
        min_x = min(x_by_col[col] - spaces["left"] for col, spaces in label_space.items())
        max_x = max(max_x, max(x_by_col[col] + col_widths[col] + spaces["right"] for col, spaces in label_space.items()))
    width = canvas.width or max_x + canvas.margin
    height = canvas.height or max_y + canvas.margin
    if min_x < 0 or min_y < 0:
        raise SchematicError("Content goes outside the canvas at top/left.")
    if max_x > width or max_y > height:
        raise SchematicError(f"Content exceeds fixed canvas {width}x{height}.")
    return Layout(canvas, font, small_font, blocks, ports, tuple(occupied), width, height)


def endpoint_point(ref: str, layout: Layout) -> tuple[int, int]:
    owner, _, pin = ref.partition(".")
    if pin:
        return layout.blocks[owner].pin_points[pin]
    if owner in layout.blocks and len(layout.blocks[owner].block.pins) == 1:
        only = layout.blocks[owner].block.pins[0]
        return layout.blocks[owner].pin_points[only.name]
    return layout.ports[owner].point


def endpoint_side(ref: str, layout: Layout) -> str:
    owner, _, pin = ref.partition(".")
    if pin:
        block = layout.blocks[owner].block
        for item in block.pins:
            if item.name == pin:
                return item.side
    if owner in layout.blocks and len(layout.blocks[owner].block.pins) == 1:
        return layout.blocks[owner].block.pins[0].side
    port = layout.ports[owner].port
    return "left" if port.direction == "output" else "right"


def _axis_positions(sizes: dict[int, int], start: int, gap: int) -> dict[int, int]:
    positions: dict[int, int] = {}
    cursor = start
    for index in sorted(sizes):
        positions[index] = cursor
        cursor += sizes[index] + gap
    return positions


def _measure_block(block: Block, canvas: Canvas, font, small_font, draw: ImageDraw.ImageDraw) -> tuple[int, int]:
    left_labels = [p.label for p in block.pins if p.side == "left"]
    right_labels = [p.label for p in block.pins if p.side == "right"]
    vertical_counts = [len([p for p in block.pins if p.side == side]) for side in ("left", "right", "top", "bottom")]
    side_h = max(vertical_counts[0], vertical_counts[1], 1) * canvas.pin_gap + canvas.block_padding_y * 2
    top_bottom_extra = max(vertical_counts[2], vertical_counts[3], 0) * 10
    h = max(canvas.min_block_height, side_h + top_bottom_extra, block.min_height or 0)
    center_text = [block.symbol] + ([block.label] if block.label else [])
    center_w = max((_text_size(draw, text, font)[0] for text in center_text), default=0) + canvas.block_padding_x * 2
    left_w = max((_text_size(draw, text, small_font)[0] for text in left_labels), default=22) + canvas.block_padding_x
    right_w = max((_text_size(draw, text, small_font)[0] for text in right_labels), default=22) + canvas.block_padding_x
    top_bottom_w = max((len([p for p in block.pins if p.side == side]) * 34 for side in ("top", "bottom")), default=0)
    w = max(canvas.min_block_width, center_w + left_w + right_w + canvas.pin_length * 2, top_bottom_w, block.min_width or 0)
    return w, h


def _pin_positions(pins: tuple[Pin, ...], rect: Rect, canvas: Canvas) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[int, int]]]:
    by_side = {side: sorted([p for p in pins if p.side == side], key=lambda p: p.order) for side in ("left", "right", "top", "bottom")}
    points: dict[str, tuple[int, int]] = {}
    labels: dict[str, tuple[int, int]] = {}
    for side, items in by_side.items():
        for idx, pin in enumerate(items):
            if side in {"left", "right"}:
                y = rect.y + canvas.block_padding_y + idx * canvas.pin_gap
                x = rect.x if side == "left" else rect.right
                points[pin.name] = (x, y)
                labels[pin.name] = (x + 8 if side == "left" else x - 8, y)
            else:
                x = _distributed(rect.x, rect.w, len(items), idx)
                y = rect.y if side == "top" else rect.bottom
                points[pin.name] = (x, y)
                labels[pin.name] = (x, y + 8 if side == "top" else y - 8)
    return points, labels


def _distributed(start: int, span: int, count: int, index: int) -> int:
    if count == 1:
        return start + span // 2
    return start + int(span * (index + 1) / (count + 1))


def _place_port(port: Port, x: int, y: int, canvas: Canvas, font, draw: ImageDraw.ImageDraw) -> PlacedPort:
    text_w, _ = _text_size(draw, port.label, font)
    symbol = "IN" if port.direction == "input" else "OUT"
    sym_w, _ = _text_size(draw, symbol, font)
    w = max(92, text_w + canvas.block_padding_x * 2 + canvas.pin_length * 2, sym_w + canvas.block_padding_x * 2)
    h = max(canvas.min_block_height, 56)
    rect = Rect(x, y, w, h)
    inner = Rect(rect.x + canvas.pin_length, rect.y, rect.w - canvas.pin_length * 2, rect.h)
    if port.direction == "input":
        point = (rect.right, rect.y + rect.h // 2)
        pin_label = "Q"
    else:
        point = (rect.left, rect.y + rect.h // 2)
        pin_label = "D"
    return PlacedPort(port, rect, inner, point, pin_label, rect)


def _content_bounds(blocks: dict[str, PlacedBlock], ports: dict[str, PlacedPort]) -> tuple[int, int, int, int]:
    rects = [b.rect for b in blocks.values()] + [p.bounds for p in ports.values()]
    if not rects:
        return 0, 0, 1, 1
    return min(r.left for r in rects), min(r.top for r in rects), max(r.right for r in rects), max(r.bottom for r in rects)


def _font(size: int):
    for name in ("DejaVuSans.ttf", "arial.ttf", "seguisym.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), str(text), font=font)
    return box[2] - box[0], box[3] - box[1]
