"""Check the functional fixed-point YAML and simulate its documented contracts.

Behavioral models use the actual YAML edges. These checks do not model physical
delays, and the renderer itself remains a drawing tool rather than an HDL engine.
"""

from pathlib import Path
import random

import yaml

from schematic_renderer.connected import connected_routes
from schematic_renderer.layout import make_layout
from schematic_renderer.model import load_schematic
from schematic_renderer.nets import named_nets


PATH = Path(__file__).resolve().parents[1] / "examples/fixed15_functional/fixed15_functional.yaml"
RAW = yaml.safe_load(PATH.read_text(encoding="utf-8"))
SCHEME = load_schematic(PATH)
EDGES = {c.chain[1]: c.chain[0] for c in SCHEME.connections}
MASK = (1 << 30) - 1


def signed15(code):
    return code - 32768 if code & 16384 else code


class Machine:
    def __init__(self):
        self.state = "IDLE"
        self.reg = dict.fromkeys(("RA", "RB", "RM", "RQ", "ACC", "CNT", "RY"), 0)

    def tick(self, a=0, b=0, valid=0, start=0, reset=0):
        r = self.reg
        v = {"RA.A": a & 32767, "RB.B": b & 32767, "RA.V": valid,
             "CTRL.C": 1, "CTRL.R": reset, "CTRL.START": start}

        def emit(block, **values):
            v.update({f"{block}.{pin}": value for pin, value in values.items()})

        def read(block, pin):
            ref = f"{block}.{pin}"
            return v[EDGES.get(ref, ref)]

        emit("RA", Q=r["RA"] & 32767, VALID=(r["RA"] >> 15) & 1)
        emit("RB", Q=r["RB"])
        emit("RM", M=r["RM"])
        emit("RQ", Q0=r["RQ"] & 1)
        emit("CNT", LAST=int(r["CNT"] == 1))
        emit("ACC", P=r["ACC"])
        emit("CTRL", CAP=int(self.state == "IDLE" and read("CTRL", "START")),
             INIT=int(self.state == "INIT"), STEP=int(self.state == "RUN"),
             EN_ACC=int(self.state == "RUN" and read("CTRL", "Q0")),
             SUB=int(self.state == "RUN" and read("CTRL", "LAST")),
             SAVE=int(self.state == "WRITE"), COUT=read("CTRL", "C"), ROUT=read("CTRL", "R"))
        a_sum, b_sum = read("SM_M", "A"), read("SM_M", "B")
        emit("SM_M", Q=((a_sum - b_sum) if read("SM_M", "SUB") else (a_sum + b_sum)) & MASK)

        # Evaluate all register inputs before committing any edge-triggered update.
        new = r.copy()
        for block in r:
            assert read(block, "C") == 1
            if read(block, "R"):
                new[block] = 0
            elif block in ("RA", "RB") and read(block, "LD"):
                new[block] = (read(block, "A") | (read(block, "V") << 15)) if block == "RA" else read(block, "B")
            elif block in ("RM", "RQ"):
                if read(block, "LD"):
                    value = read(block, "D")
                    new[block] = (signed15(value) & MASK) if block == "RM" else value
                elif read(block, "SH"):
                    new[block] = ((r[block] << 1) & MASK) if block == "RM" else r[block] >> 1
            elif block == "ACC":
                if read(block, "CLR"):
                    new[block] = 0
                elif read(block, "EN"):
                    new[block] = read(block, "D")
            elif block == "CNT":
                if read(block, "LD15"):
                    new[block] = 15
                elif read(block, "DEC"):
                    new[block] = r[block] - 1
            elif block == "RY" and read(block, "LD"):
                new[block] = read(block, "D") | (read(block, "VI") << 30)
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
        return new["RY"] & MASK, (new["RY"] >> 30) & 1


def test_fixed_functional_connections_widths_and_routes():
    layout = make_layout(SCHEME)
    names = named_nets(SCHEME)
    assert SCHEME.canvas.wiring == "connected"
    routes, _ = connected_routes(SCHEME, layout)
    assert len(routes) == len(SCHEME.connections) == len(EDGES) == 35
    assert len(SCHEME.blocks) == 9
    assert {b.symbol for b in SCHEME.blocks.values()} == {"RG", "CT", "SM", "FSM"}
    ins = {f"{bid}.{p.name}" for bid, block in SCHEME.blocks.items() for p in block.inputs}
    outs = {f"{bid}.{p.name}" for bid, block in SCHEME.blocks.items() for p in block.outputs}
    ext_in, ext_out = set(RAW["design"]["external_inputs"]), set(RAW["design"]["external_outputs"])
    assert ext_in <= ins and ext_out <= outs
    assert set(EDGES) == ins - ext_in
    assert set(EDGES.values()) | ext_out == outs
    assert set(names) == ins | outs
    for bid, block in SCHEME.blocks.items():
        assert set(RAW["blocks"][bid]["widths"]) == {p.name for p in block.pins}
    for sink, source in EDGES.items():
        assert source in outs and sink in ins
        sb, sp = source.split(".")
        db, dp = sink.split(".")
        assert RAW["blocks"][sb]["widths"][sp] == RAW["blocks"][db]["widths"][dp]
    logic = load_schematic(PATH.with_name("fixed15_functional.logic.yaml"))
    assert {c.chain for c in logic.connections} == {c.chain for c in SCHEME.connections}
    assert logic.net_names == SCHEME.net_names


def test_only_schematic_and_outward_external_arrows():
    layout = make_layout(SCHEME)
    assert all(p.kind == "polyline" for p in SCHEME.primitives)
    external = set(RAW["design"]["external_inputs"] + RAW["design"]["external_outputs"])
    assert len(SCHEME.primitives) == len(external) == 10
    assert {p.data["terminal"] for p in SCHEME.primitives} == external
    for primitive in SCHEME.primitives:
        block, name = primitive.data["terminal"].split(".")
        placed = layout.blocks[block]
        pin = next(p for p in placed.block.pins if p.name == name)
        assert pin.label == SCHEME.net_names[f"{block}.{name}"]
        x, y = placed.pin_points[name]
        direction = -1 if pin.side == "left" else 1
        tip = x + direction * layout.canvas.pin_length
        assert primitive.data["points"] == [
            [tip - direction * 8, y - 5], [tip, y], [tip - direction * 8, y + 5]]


def test_all_multiplier_codes_for_extreme_multiplicands():
    for a in (-16384, -1, 0, 1, 16383):
        for b in range(32768):
            m, q, acc = a & MASK, b, 0
            for i in range(15):
                if q & 1:
                    acc = (acc - m if i == 14 else acc + m) & MASK
                m, q = (m << 1) & MASK, q >> 1
            assert acc == (a * signed15(b)) & MASK


def test_wired_behavior_latency_and_sync():
    rng = random.Random(150530)
    cases = [(rng.randrange(-16384, 16384), rng.randrange(-16384, 16384)) for _ in range(2000)]
    boundary = (-16384, -16383, -8192, -72, -32, -1, 0, 1, 32, 48, 8191, 16382, 16383)
    cases += [(a, b) for a in boundary for b in boundary]
    machine = Machine()
    machine.tick(reset=1)
    for index, (a, b) in enumerate(cases):
        previous = machine.reg["RY"]
        valid = index % 2
        machine.tick(a, b, valid, start=1)
        assert machine.state == "INIT"
        for _ in range(16):  # initialization, then fifteen RUN edges
            machine.tick(17, -19, 1 - valid, start=1)
            assert machine.reg["RY"] == previous
            assert machine.state != "DONE"
        assert machine.state == "WRITE"
        assert machine.reg["CNT"] == 0
        assert machine.reg["ACC"] == (a * b) & MASK
        assert machine.tick(start=1) == ((a * b) & MASK, valid)
        assert machine.state == "DONE"
        result = machine.reg["RY"]
        machine.tick(start=1)
        assert machine.state == "DONE" and machine.reg["RY"] == result
        machine.tick(start=0)
        assert machine.state == "IDLE" and machine.reg["RY"] == result


def test_reset_aborts_each_phase():
    for elapsed in range(20):
        machine = Machine()
        machine.tick(-16384, -16384, 1, start=1)
        for _ in range(elapsed):
            machine.tick(start=1)
        machine.tick(start=1, reset=1)
        assert machine.state == "IDLE"
        assert all(value == 0 for value in machine.reg.values())


def test_fixed_point_scale_examples():
    for a, b, product in [(48, -72, -3.375), (1, 1, 1 / 1024),
                          (-16384, -16384, 262144), (-16384, 16383, -262128)]:
        machine = Machine()
        machine.tick(a, b, 1, start=1)
        for _ in range(17):
            code, valid = machine.tick()
        value = code - (1 << 30) if code & (1 << 29) else code
        assert value / 1024 == product
        assert valid == 1 and machine.state == "DONE"
