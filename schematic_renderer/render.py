from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .layout import Layout, PlacedBlock, _font, endpoint_point, endpoint_side, make_layout
from .model import Pin, Primitive, Schematic
from .nets import named_nets
from .router import RoutedConnection, route_connections
from .connected import connected_routes, draw_connected


class _RasterDraw(ImageDraw.ImageDraw):
    def line(self, xy, fill=None, width=0, joint=None):
        # Pillow offsets even-width strokes differently when endpoints reverse.
        if len(xy) == 2 and (xy[0][0] == xy[1][0] or xy[0][1] == xy[1][1]):
            xy = sorted(xy)
        super().line(xy, fill=fill, width=width, joint=joint)


def render_schematic(schematic: Schematic, output: str | Path) -> None:
    layout = make_layout(schematic)
    routed = route_connections(schematic.connections, layout) if schematic.canvas.wiring == "routed" else ()
    segments = ()
    if schematic.canvas.wiring == "connected":
        routed, segments = connected_routes(schematic, layout)
    scale = max(1, int(layout.canvas.scale))
    is_svg = Path(output).suffix.lower() == ".svg"
    if is_svg:
        from .svg import SVGDraw
        draw = SVGDraw(layout.width, layout.height, layout.canvas.background, scale)
    else:
        mode = "L" if schematic.canvas.wiring == "connected" else "RGB"
        image = Image.new(mode, (layout.width, layout.height), layout.canvas.background)
        draw = _RasterDraw(image)
    _draw_primitives(draw, schematic.primitives)
    for port in layout.ports.values():
        _draw_port(draw, port, layout)
    for block in layout.blocks.values():
        _draw_block(draw, block, layout)
    if schematic.canvas.wiring == "connected":
        draw_connected(draw, routed, segments, layout)
    else:
        for routed_connection in routed:
            _draw_connection(draw, routed_connection, layout)
    if schematic.canvas.wiring == "named":
        _draw_named_nets(draw, schematic, layout)
    if is_svg:
        draw.save(output)
        return
    if scale != 1:
        image = image.resize((layout.width * scale, layout.height * scale), Image.Resampling.LANCZOS)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def _draw_named_nets(draw, schematic: Schematic, layout: Layout) -> None:
    for ref, name in named_nets(schematic).items():
        x, y = endpoint_point(ref, layout)
        side = endpoint_side(ref, layout)
        length = layout.canvas.pin_length + 6
        if side == "left":
            end, text, anchor = (x - length, y), (x - length - 4, y), "rm"
        elif side == "right":
            end, text, anchor = (x + length, y), (x + length + 4, y), "lm"
        else:
            raise ValueError("Named wiring currently requires left/right pins.")
        draw.line([(x, y), end], fill="black", width=layout.canvas.line_width)
        _text(draw, text, name, layout.small_font, anchor)


def _draw_block(draw, placed: PlacedBlock, layout: Layout) -> None:
    c = layout.canvas
    r = placed.rect
    inner = placed.inner_rect
    draw.rectangle((r.left, r.top, r.right, r.bottom), outline="black", width=c.line_width)
    draw.line([(inner.left, r.top), (inner.left, r.bottom)], fill="black", width=c.line_width)
    draw.line([(inner.right, r.top), (inner.right, r.bottom)], fill="black", width=c.line_width)
    _center_text(draw, placed.block.id, (r.left, r.top - 22, r.right, r.top - 4), layout.small_font)
    central = placed.block.symbol if not placed.block.label else f"{placed.block.symbol}\n{placed.block.label}"
    _center_multiline(draw, central, (inner.left, inner.top, inner.right, inner.bottom), layout.font)
    for pin in placed.block.pins:
        point = placed.pin_points[pin.name]
        _draw_pin(draw, point, pin, placed, layout)


def _draw_port(draw, placed, layout: Layout) -> None:
    c = layout.canvas
    r = placed.rect
    inner = placed.inner_rect
    draw.rectangle((r.left, r.top, r.right, r.bottom), outline="black", width=c.line_width)
    if placed.port.direction == "input":
        draw.line([(inner.right, r.top), (inner.right, r.bottom)], fill="black", width=c.line_width)
        draw.line([(r.right - c.pin_length, placed.point[1]), (r.right + c.pin_length, placed.point[1])], fill="black", width=c.line_width)
        _text(draw, (r.right - 8, placed.point[1] - 8), placed.pin_label, layout.small_font, "rm")
    else:
        draw.line([(inner.left, r.top), (inner.left, r.bottom)], fill="black", width=c.line_width)
        draw.line([(r.left - c.pin_length, placed.point[1]), (r.left + c.pin_length, placed.point[1])], fill="black", width=c.line_width)
        _text(draw, (r.left + 8, placed.point[1] - 8), placed.pin_label, layout.small_font, "lm")
    symbol = "IN" if placed.port.direction == "input" else "OUT"
    _center_text(draw, placed.port.id, (r.left, r.top - 22, r.right, r.top - 4), layout.small_font)
    _center_multiline(draw, f"{symbol}\n{placed.port.label}", (inner.left, inner.top, inner.right, inner.bottom), layout.small_font)


def _draw_pin(draw, point: tuple[int, int], pin: Pin, placed: PlacedBlock, layout: Layout) -> None:
    c = layout.canvas
    x, y = point
    if pin.side == "left":
        inner = (placed.inner_rect.left, y)
        line = [(x - c.pin_length, y), inner]
        anchor = "lm"
        text_pos = (x + 8, y - 8)
    elif pin.side == "right":
        inner = (placed.inner_rect.right, y)
        line = [(x + c.pin_length, y), inner]
        anchor = "rm"
        text_pos = (x - 8, y - 8)
    elif pin.side == "top":
        inner = (x, y + c.pin_length)
        line = [(x, y - c.pin_length), inner]
        anchor = "mm"
        text_pos = (x, y + 4)
    else:
        inner = (x, y - c.pin_length)
        line = [(x, y + c.pin_length), inner]
        anchor = "mm"
        text_pos = (x, y - 18)
    draw.line(line, fill="black", width=c.line_width)
    _text(draw, text_pos, pin.label, layout.small_font, anchor)
    if pin.marker and pin.marker.lower() in {"invert", "инверсия"}:
        draw.ellipse((inner[0] - 4, inner[1] - 4, inner[0] + 4, inner[1] + 4), outline="black", width=c.line_width)
    if pin.marker and pin.marker.lower() in {"clock", "clk", "такт"}:
        if pin.side in {"left", "right"}:
            direction = 1 if pin.side == "left" else -1
            tri = [(inner[0], inner[1] - 6), (inner[0], inner[1] + 6), (inner[0] + 9 * direction, inner[1])]
        else:
            direction = 1 if pin.side == "top" else -1
            tri = [(inner[0] - 6, inner[1]), (inner[0] + 6, inner[1]), (inner[0], inner[1] + 9 * direction)]
        draw.polygon(tri, outline="black", fill=None)


def _draw_connection(draw, routed: RoutedConnection, layout: Layout) -> None:
    for a, b in routed.segments:
        draw.line([a, b], fill="black", width=layout.canvas.line_width)
    if routed.connection.label and routed.points:
        mid = routed.points[len(routed.points) // 2]
        draw.text((mid[0] + 4, mid[1] + 4), routed.connection.label, fill="black", font=layout.small_font)
    seen = set()
    for point in routed.points[1:-1]:
        if point in seen:
            _dot(draw, point, layout.canvas.line_width)
        seen.add(point)


def _draw_primitives(draw, primitives: tuple[Primitive, ...]) -> None:
    for primitive in primitives:
        d = primitive.data
        if primitive.kind == "line":
            draw.line([tuple(d["from"]), tuple(d["to"])], fill=d.get("color", "black"), width=int(d.get("width", 1)))
        elif primitive.kind == "polyline":
            draw.line([tuple(p) for p in d["points"]], fill=d.get("color", "black"), width=int(d.get("width", 1)))
        elif primitive.kind == "rect":
            x, y = d["position"]
            w, h = d["size"]
            draw.rectangle((x, y, x + w, y + h), outline=d.get("color", "black"), width=int(d.get("width", 1)))
        elif primitive.kind == "text":
            draw.text(tuple(d["position"]), str(d.get("text", "")), fill=d.get("color", "black"),
                      font=_font(int(d["font_size"])) if "font_size" in d else None)


def _dot(draw, point: tuple[int, int], width: int) -> None:
    x, y = point
    r = max(3, width + 1)
    draw.ellipse((x - r, y - r, x + r, y + r), fill="black")


def _center_text(draw, text: str, box, font) -> None:
    left, top, right, bottom = box
    bbox = draw.textbbox((0, 0), text, font=font)
    x = left + (right - left - (bbox[2] - bbox[0])) // 2
    y = top + (bottom - top - (bbox[3] - bbox[1])) // 2
    draw.text((x, y), text, fill="black", font=font)


def _center_multiline(draw, text: str, box, font) -> None:
    lines = text.splitlines()
    left, top, right, bottom = box
    sizes = [_measure(draw, line, font) for line in lines]
    total_h = sum(h for _, h in sizes) + (len(lines) - 1) * 4
    y = top + (bottom - top - total_h) // 2
    for line, (w, h) in zip(lines, sizes):
        draw.text((left + (right - left - w) // 2, y), line, fill="black", font=font)
        y += h + 4


def _text(draw, xy, text, font, anchor):
    try:
        draw.text(xy, text, fill="black", font=font, anchor=anchor)
    except TypeError:
        draw.text(xy, text, fill="black", font=font)


def _measure(draw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]
