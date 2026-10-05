from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from .errors import SchematicError


SIDE_ALIASES = {
    "left": "left",
    "right": "right",
    "top": "top",
    "bottom": "bottom",
    "слева": "left",
    "справа": "right",
    "сверху": "top",
    "снизу": "bottom",
}
MARKERS = {"invert", "clock", "инверсия", "такт", "clk"}
RANGE_RE = re.compile(r"^(.+)\[(\d+):(\d+)\]$")


@dataclass(frozen=True)
class Canvas:
    layout: str = "grid"
    wiring: str = "routed"
    background: str = "white"
    scale: int = 3
    margin: int = 40
    width: int | None = None
    height: int | None = None
    grid_x: int = 220
    grid_y: int = 140
    route_step: int = 20
    font_size: int = 16
    small_font_size: int = 13
    line_width: int = 2
    pin_length: int = 18
    block_padding_x: int = 16
    block_padding_y: int = 16
    pin_gap: int = 24
    min_block_width: int = 96
    min_block_height: int = 72
    column_gap: int = 160
    row_gap: int = 70


@dataclass(frozen=True)
class Pin:
    name: str
    label: str
    side: str
    order: int
    marker: str | None = None


@dataclass(frozen=True)
class Block:
    id: str
    symbol: str
    position: tuple[int, int]
    label: str | None = None
    inputs: tuple[Pin, ...] = ()
    outputs: tuple[Pin, ...] = ()
    min_width: int | None = None
    min_height: int | None = None
    offset: tuple[int, int] = (0, 0)

    @property
    def pins(self) -> tuple[Pin, ...]:
        return self.inputs + self.outputs


@dataclass(frozen=True)
class Port:
    id: str
    label: str
    direction: str
    position: tuple[int, int]
    offset: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class Connection:
    chain: tuple[str, ...]
    points: tuple[tuple[int, int], ...] = ()
    label: str | None = None


@dataclass(frozen=True)
class Primitive:
    kind: str
    data: dict[str, Any]


@dataclass(frozen=True)
class Schematic:
    canvas: Canvas
    blocks: dict[str, Block] = field(default_factory=dict)
    ports: dict[str, Port] = field(default_factory=dict)
    connections: tuple[Connection, ...] = ()
    primitives: tuple[Primitive, ...] = ()
    net_names: dict[str, str] = field(default_factory=dict)


def load_schematic(path: str | Path) -> Schematic:
    with Path(path).open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise SchematicError("YAML root must be a mapping.")
    return parse_schematic(raw)


def parse_schematic(raw: dict[str, Any]) -> Schematic:
    canvas = Canvas(**(raw.get("canvas") or {}))
    if canvas.wiring not in {"routed", "named", "connected"}:
        raise SchematicError("canvas.wiring must be routed, named or connected.")
    if canvas.layout not in {"grid", "absolute"}:
        raise SchematicError("canvas.layout must be grid or absolute.")
    blocks = _parse_blocks(raw.get("blocks") or {})
    ports = _parse_ports(raw.get("ports") or {})
    _check_duplicate_ids(blocks, ports)
    connections = tuple(_parse_connection(item) for item in raw.get("connections") or [])
    primitives = tuple(_parse_primitive(item) for item in raw.get("primitives") or [])
    net_names = {str(ref): str(name) for ref, name in (raw.get("net_names") or {}).items()}
    schematic = Schematic(canvas, blocks, ports, connections, primitives, net_names)
    _validate_references(schematic)
    for ref in net_names:
        resolve_ref(ref, schematic)
    return schematic


def _parse_blocks(raw_blocks: dict[str, Any]) -> dict[str, Block]:
    if not isinstance(raw_blocks, dict):
        raise SchematicError("blocks must be a mapping.")
    blocks: dict[str, Block] = {}
    for block_id, data in raw_blocks.items():
        if block_id in blocks:
            raise SchematicError(f"Duplicate block id: {block_id}")
        if not isinstance(data, dict):
            raise SchematicError(f"Block {block_id} must be a mapping.")
        position = _pair(data.get("position", [0, 0]), f"block {block_id}.position")
        inputs = _parse_pins(data.get("inputs", ()), "left", f"{block_id}.inputs")
        outputs = _parse_pins(data.get("outputs", ()), "right", f"{block_id}.outputs")
        blocks[str(block_id)] = Block(
            id=str(block_id),
            symbol=str(data.get("symbol", block_id)),
            label=_optional_str(data.get("label")),
            position=position,
            inputs=inputs,
            outputs=outputs,
            min_width=_optional_int(data.get("min_width")),
            min_height=_optional_int(data.get("min_height")),
            offset=_pair(data.get("offset", [0, 0]), f"block {block_id}.offset"),
        )
    return blocks


def _parse_ports(raw_ports: dict[str, Any]) -> dict[str, Port]:
    if not isinstance(raw_ports, dict):
        raise SchematicError("ports must be a mapping.")
    ports: dict[str, Port] = {}
    for port_id, data in raw_ports.items():
        if port_id in ports:
            raise SchematicError(f"Duplicate port id: {port_id}")
        if not isinstance(data, dict):
            raise SchematicError(f"Port {port_id} must be a mapping.")
        direction = str(data.get("direction", "input")).lower()
        if direction not in {"input", "output"}:
            raise SchematicError(f"Port {port_id} direction must be input or output.")
        ports[str(port_id)] = Port(
            id=str(port_id),
            label=str(data.get("label", port_id)),
            direction=direction,
            position=_pair(data.get("position", [0, 0]), f"port {port_id}.position"),
            offset=_pair(data.get("offset", [0, 0]), f"port {port_id}.offset"),
        )
    return ports


def _parse_pins(raw_pins: Any, default_side: str, context: str) -> tuple[Pin, ...]:
    expanded: list[Any] = []
    for item in raw_pins or []:
        if isinstance(item, str):
            expanded.extend(_expand_range(item))
        else:
            expanded.append(item)
    pins: list[Pin] = []
    seen: set[str] = set()
    for index, item in enumerate(expanded):
        if isinstance(item, str):
            data = {"name": item, "label": item}
        elif isinstance(item, dict):
            data = dict(item)
        else:
            raise SchematicError(f"{context}[{index}] must be a string or mapping.")
        name = str(data.get("name") or data.get("id") or data.get("label"))
        if not name or name == "None":
            raise SchematicError(f"{context}[{index}] has no name.")
        if name in seen:
            raise SchematicError(f"Duplicate pin {name} in {context}.")
        seen.add(name)
        side = SIDE_ALIASES.get(str(data.get("side", default_side)).lower())
        if not side:
            raise SchematicError(f"Pin {context}.{name} has unknown side.")
        marker = data.get("marker")
        if marker is not None and str(marker).lower() not in MARKERS:
            raise SchematicError(f"Pin {context}.{name} has unknown marker {marker}.")
        pins.append(Pin(name, str(data.get("label", name)), side, int(data.get("order", index)), _optional_str(marker)))
    return tuple(sorted(pins, key=lambda p: (p.side, p.order, p.name)))


def _expand_range(value: str) -> list[str]:
    match = RANGE_RE.match(value)
    if not match:
        return [value]
    prefix, start_s, end_s = match.groups()
    start, end = int(start_s), int(end_s)
    step = 1 if end >= start else -1
    return [f"{prefix}{idx}" for idx in range(start, end + step, step)]


def _parse_connection(item: Any) -> Connection:
    if isinstance(item, str):
        chain = tuple(part.strip() for part in item.split("->") if part.strip())
        if len(chain) < 2:
            raise SchematicError(f"Connection must contain at least two endpoints: {item}")
        return Connection(chain=chain)
    if isinstance(item, dict):
        chain_raw = item.get("chain")
        if not chain_raw and item.get("from") and item.get("to"):
            chain_raw = [item["from"], item["to"]]
        if isinstance(chain_raw, str):
            chain = tuple(part.strip() for part in chain_raw.split("->") if part.strip())
        else:
            chain = tuple(str(part) for part in chain_raw or [])
        if len(chain) < 2:
            raise SchematicError(f"Connection mapping must contain chain/from/to: {item}")
        points = tuple(_pair(p, "connection.points") for p in item.get("points", ()))
        return Connection(chain=chain, points=points, label=_optional_str(item.get("label")))
    raise SchematicError(f"Connection must be a string or mapping: {item}")


def _parse_primitive(item: Any) -> Primitive:
    if not isinstance(item, dict) or "type" not in item:
        raise SchematicError(f"Primitive must be a mapping with type: {item}")
    data = dict(item)
    kind = str(data.pop("type"))
    return Primitive(kind, data)


def _validate_references(schematic: Schematic) -> None:
    for connection in schematic.connections:
        for ref in connection.chain:
            resolve_ref(ref, schematic)


def resolve_ref(ref: str, schematic: Schematic) -> tuple[str, str | None]:
    if "." in ref:
        owner, pin = ref.split(".", 1)
        if owner not in schematic.blocks:
            raise SchematicError(f"Unknown block in reference {ref}.")
        if pin not in {p.name for p in schematic.blocks[owner].pins}:
            raise SchematicError(f"Unknown pin in reference {ref}.")
        return owner, pin
    if ref in schematic.ports:
        return ref, None
    if ref in schematic.blocks:
        pins = schematic.blocks[ref].pins
        if len(pins) != 1:
            raise SchematicError(f"Ambiguous reference {ref}: specify one of {', '.join(p.name for p in pins)}.")
        return ref, pins[0].name
    raise SchematicError(f"Unknown reference {ref}.")


def _check_duplicate_ids(blocks: dict[str, Block], ports: dict[str, Port]) -> None:
    overlap = sorted(set(blocks) & set(ports))
    if overlap:
        raise SchematicError(f"IDs used both as block and port: {', '.join(overlap)}")


def _pair(value: Any, context: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise SchematicError(f"{context} must be [x, y].")
    return int(value[0]), int(value[1])


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
