"""Connectivity checks and a behavioral model of the YAML's stated contracts.

The drawing renderer is not an HDL simulator. The model below evaluates the
documented blocks through actual YAML edges, including synchronous updates.
"""

from pathlib import Path
import random

import yaml
from PIL import Image, ImageDraw

from schematic_renderer.layout import Rect, _font, make_layout
from schematic_renderer.connected import connected_routes
from schematic_renderer.model import load_schematic
from schematic_renderer.nets import named_nets


PATH = Path(__file__).resolve().parents[1] / "examples/float15_functional/float15_functional.yaml"
RAW = yaml.safe_load(PATH.read_text(encoding="utf-8"))
SCHEME = load_schematic(PATH)
EDGES = {c.chain[1]: c.chain[0] for c in SCHEME.connections}


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def expected(a, b):
    product = (a & 511) * (b & 511)
    if not product:
        return 0, 0
    shift = 18 - product.bit_length()
    exponent = signed(a >> 10, 5) + signed(b >> 10, 5) - shift
    if not -16 <= exponent <= 15:
        return 0, 1
    fraction = (product << shift) >> 9
    sign = ((a ^ b) >> 9) & 1
    return ((exponent & 31) << 10) | (sign << 9) | fraction, 0


class Machine:
    def __init__(self):
        self.state = "IDLE"
        self.reg = dict.fromkeys(("RA", "RB", "RM", "RQ", "ACC", "CNT", "RY"), 0)

    def tick(self, a=0, b=0, valid=0, start=0, reset=0):
        r = self.reg
        v = {"RA.A": a, "RB.B": b, "RA.V": valid,
             "CTRL.C": 1, "CTRL.R": reset, "CTRL.START": start}

        def emit(block, **values):
            v.update({f"{block}.{pin}": value for pin, value in values.items()})

        def read(block, pin):
            ref = f"{block}.{pin}"
            return v[EDGES.get(ref, ref)]

        for block in ("RA", "RB"):
            emit(block, F=r[block] & 511, S=(r[block] >> 9) & 1,
                 E=(r[block] >> 10) & 31)
        emit("RA", VALID=(r["RA"] >> 15) & 1)
        emit("RM", M=r["RM"])
        emit("RQ", Q0=r["RQ"] & 1)
        emit("ACC", P=r["ACC"])
        emit("CNT", LAST=int(r["CNT"] == 1))
        emit("CTRL", CAP=int(self.state == "IDLE" and read("CTRL", "START")),
             INIT=int(self.state == "INIT"), STEP=int(self.state == "RUN"),
             ADD=int(self.state == "RUN" and read("CTRL", "Q0")),
             SAVE=int(self.state == "WRITE"), COUT=read("CTRL", "C"),
             ROUT=read("CTRL", "R"))
        emit("SM_M", Q=(read("SM_M", "A") + read("SM_M", "B")) & 262143)
        emit("SIGN", S=read("SIGN", "A") ^ read("SIGN", "B"))
        emit("SM_E", Q=(signed(read("SM_E", "A"), 5) + signed(read("SM_E", "B"), 5)) & 127)
        p = read("LZ", "P")
        emit("LZ", Z=int(p == 0), K=18 - p.bit_length() if p else 0)
        emit("NORM", F=((read("NORM", "P") << read("NORM", "K")) & 262143) >> 9)
        emit("SM_N", Q=(signed(read("SM_N", "A"), 7) - read("SM_N", "B")) & 127)
        e = signed(read("FORMAT", "E"), 7)
        zero = read("FORMAT", "Z")
        error = int(not zero and not -16 <= e <= 15)
        word = 0 if zero or error else ((e & 31) << 10) | (read("FORMAT", "S") << 9) | read("FORMAT", "F")
        emit("FORMAT", Y=word, ERR=error)

        # All right-hand sides use pre-edge values, including LAST and Q0.
        new = r.copy()
        for block in r:
            assert read(block, "C") == 1
            if read(block, "R"):
                new[block] = 0
            elif block in ("RA", "RB") and read(block, "LD"):
                new[block] = (read(block, "A") | (read(block, "V") << 15)) if block == "RA" else read(block, "B")
            elif block in ("RM", "RQ"):
                if read(block, "LD"):
                    new[block] = read(block, "D")
                elif read(block, "SH"):
                    new[block] = ((r[block] << 1) & 262143) if block == "RM" else r[block] >> 1
            elif block == "ACC":
                if read(block, "CLR"):
                    new[block] = 0
                elif read(block, "EN"):
                    new[block] = read(block, "D")
            elif block == "CNT":
                if read(block, "LD9"):
                    new[block] = 9
                elif read(block, "DEC"):
                    new[block] = r[block] - 1
            elif block == "RY" and read(block, "LD"):
                new[block] = read(block, "D") | (read(block, "DI") << 15) | (read(block, "VI") << 16)
        if reset:
            self.state = "IDLE"
        elif self.state == "IDLE" and start:
            self.state = "INIT"
        elif self.state == "INIT":
            self.state = "RUN"
        elif self.state == "RUN" and read("CTRL", "LAST"):
            self.state = "WRITE"
        elif self.state == "WRITE":
            self.state = "DONE"
        elif self.state == "DONE" and not start:
            self.state = "IDLE"
        self.reg = new
        return new["RY"] & 32767, (new["RY"] >> 15) & 1, (new["RY"] >> 16) & 1


def test_functional_yaml_is_complete_and_width_consistent():
    names = named_nets(SCHEME)
    layout = make_layout(SCHEME)
    assert SCHEME.canvas.wiring == "connected"
    routes, _ = connected_routes(SCHEME, layout)
    assert len(routes) == len(SCHEME.connections) == 48
    ins = {f"{bid}.{p.name}" for bid, b in SCHEME.blocks.items() for p in b.inputs}
    outs = {f"{bid}.{p.name}" for bid, b in SCHEME.blocks.items() for p in b.outputs}
    external_in = set(RAW["design"]["external_inputs"])
    external_out = set(RAW["design"]["external_outputs"])
    assert external_in <= ins and external_out <= outs
    assert set(EDGES) == ins - external_in
    assert len(EDGES) == len(SCHEME.connections)
    assert set(EDGES.values()) | external_out == outs
    assert set(names) == ins | outs
    assert not any(b.symbol in {"MUL", "AND", "OR", "NOT"} for b in SCHEME.blocks.values())
    for block in SCHEME.blocks.values():
        assert set(RAW["blocks"][block.id]["widths"]) == {p.name for p in block.pins}
    for sink, source in EDGES.items():
        assert source in outs and sink in ins
        sb, sp = source.split(".")
        db, dp = sink.split(".")
        assert RAW["blocks"][sb]["widths"][sp] == RAW["blocks"][db]["widths"][dp]


def test_all_nine_bit_mantissa_products():
    for a in range(512):
        for b in range(512):
            acc, m, q = 0, a, b
            for _ in range(9):
                if q & 1:
                    acc += m
                m <<= 1
                q >>= 1
            assert acc == a * b < (1 << 18)


def test_connected_behavior_and_exact_latency():
    rng = random.Random(150509)
    cases = [(rng.randrange(32768), rng.randrange(32768)) for _ in range(1000)]
    fields = [(f, e, s) for f in (0, 1, 255, 256, 511) for e in (-16, -15, 0, 15) for s in (0, 1)]
    words = [((e & 31) << 10) | (s << 9) | f for f, e, s in fields]
    cases += [(a, b) for a in words for b in words]
    machine = Machine()
    machine.tick(reset=1)
    for index, (a, b) in enumerate(cases):
        previous = machine.reg["RY"]
        valid = index % 2
        machine.tick(a, b, valid, start=1)  # n: accepted
        assert machine.state == "INIT"
        for _ in range(10):  # n+1 through n+10
            machine.tick(a ^ 32767, b ^ 32767, 1 - valid, start=1)
            assert machine.reg["RY"] == previous
            assert machine.state != "DONE"
        assert machine.state == "WRITE"
        assert machine.reg["ACC"] == (a & 511) * (b & 511)
        assert machine.tick(start=1) == (*expected(a, b), valid)  # n+11
        assert machine.state == "DONE"
        machine.tick(start=1)
        assert machine.state == "DONE"
        machine.tick(start=0)
        assert machine.state == "IDLE"


def test_reset_aborts_each_state_and_clears_result():
    for elapsed in range(14):
        machine = Machine()
        machine.tick(511, 511, 1, start=1)
        for _ in range(elapsed):
            machine.tick(start=1)
        machine.tick(start=1, reset=1)
        assert machine.state == "IDLE"
        assert all(value == 0 for value in machine.reg.values())


def test_known_values_zero_sign_normalization_and_range():
    # 0.5 * -0.5 = -0.5 * 2^-1; opposite signs propagate independently.
    assert expected(256, 256 | 512) == ((31 << 10) | 512 | 256, 0)
    assert expected(0, (15 << 10) | 511 | 512) == (0, 0)
    assert expected((15 << 10) | 511, (15 << 10) | 511) == (0, 1)
    assert expected((16 << 10) | 1, (16 << 10) | 1) == (0, 1)


def test_arrow_directions_and_annotation_geometry():
    layout = make_layout(SCHEME)
    assert all(p.kind != "text" for p in SCHEME.primitives)
    _, segments = connected_routes(SCHEME, layout)
    arrows = [p for p in SCHEME.primitives if p.kind == "polyline"]
    external = set(RAW["design"]["external_inputs"] + RAW["design"]["external_outputs"])
    assert len(arrows) == len(external) == 11
    assert {p.data["terminal"] for p in arrows} == external
    for primitive in arrows:
        bid, name = primitive.data["terminal"].split(".")
        placed = layout.blocks[bid]
        pin = next(p for p in placed.block.pins if p.name == name)
        x, y = placed.pin_points[pin.name]
        direction = -1 if pin.side == "left" else 1
        tip = x + direction * layout.canvas.pin_length
        points = primitive.data["points"]
        assert points == [[tip - 8 * direction, y - 5], [tip, y], [tip - 8 * direction, y + 5]]
        arrow_box = Rect(min(p[0] for p in points), y - 5, 8, 10)
        assert not any(arrow_box.intersects(b.rect) for b in layout.blocks.values())
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    annotations = []
    for primitive in SCHEME.primitives:
        if primitive.kind != "text":
            continue
        d = primitive.data
        x0, y0, x1, y1 = draw.textbbox(tuple(d["position"]), d["text"], font=_font(d["font_size"]))
        box = Rect(x0, y0, x1 - x0, y1 - y0)
        assert 0 <= x0 < x1 <= layout.width and 0 <= y0 < y1 <= layout.height
        assert not any(box.intersects(b.rect) for b in layout.blocks.values())
        assert not any(box.intersects(previous) for previous in annotations)
        for a, b, _ in segments:
            wire = Rect(min(a[0], b[0]) - 2, min(a[1], b[1]) - 2,
                        abs(a[0] - b[0]) + 4, abs(a[1] - b[1]) + 4)
            assert not box.intersects(wire), d["text"]
        annotations.append(box)


def test_continuous_layout_preserves_original_logic():
    original = load_schematic(PATH.with_name("float15_functional.logic.yaml"))
    assert set(original.blocks) == set(SCHEME.blocks)
    assert {c.chain for c in original.connections} == {c.chain for c in SCHEME.connections}
    assert original.net_names == SCHEME.net_names
    for bid in SCHEME.blocks:
        assert {(p.name, p.side) for p in SCHEME.blocks[bid].pins} == {
            (p.name, p.side) for p in original.blocks[bid].pins}
