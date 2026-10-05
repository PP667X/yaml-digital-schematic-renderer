from collections import Counter
import random

import pytest

from schematic_renderer.errors import SchematicError
from schematic_renderer.generate import build_reference15
from schematic_renderer.layout import make_layout
from schematic_renderer.model import parse_schematic
from schematic_renderer.nets import named_nets


class Simulator:
    """Evaluate the exported pin connections, not the generator's arithmetic."""
    def __init__(self, raw):
        self.schematic = parse_schematic(raw)
        self.names = named_nets(self.schematic)
        self.state = {self.names[f"{b.id}.Q"]: 0
                      for b in self.schematic.blocks.values() if b.symbol == "D"}

    def edge(self, a, b, sync):
        values = {f"{name}{i:02d}": (word >> i) & 1
                  for name, word in (("A", a), ("B", b)) for i in range(15)}
        values.update(SYNC_IN=sync, CLK=1)
        values.update(self.state)
        for block in self.schematic.blocks.values():
            if block.symbol == "D":
                continue
            inputs = [values[self.names[f"{block.id}.{p.name}"]] for p in block.inputs]
            x, y = inputs
            result = {"AND": x & y, "OR": x | y, "XOR": x ^ y}[block.symbol]
            values[self.names[f"{block.id}.Q"]] = result
        self.state = {self.names[f"{block.id}.Q"]: values[self.names[f"{block.id}.D"]]
                      for block in self.schematic.blocks.values() if block.symbol == "D"}
        return sum(self.state[f"Y{i:02d}"] << i for i in range(15)), self.state["SYNC_OUT"]


def reference(a, b):
    product = ((a & 1023) * (b & 1023)) >> 10
    exponent = (((a >> 10) & 15) + ((b >> 10) & 15)) & 15
    sign = ((a >> 14) ^ (b >> 14)) & 1
    return product | (exponent << 10) | (sign << 14)


def test_exported_gate_network_and_sync_match_reference():
    sim = Simulator(build_reference15())
    rng = random.Random(314159)
    vectors = [(a, b, 1) for a in [0, 1, 511, 512, 1023, 16384, 32767]
               for b in [0, 1, 511, 512, 1023, 16384, 32767]]
    vectors += [(ea << 10 | 1023, eb << 10 | 1023, (ea + eb) & 1)
                for ea in range(16) for eb in range(16)]
    vectors += [(rng.randrange(32768), rng.randrange(32768), rng.randrange(2)) for _ in range(1000)]
    previous = (0, 0)
    for a, b, sync in vectors + [(0, 0, 0)]:
        assert sim.edge(a, b, sync) == previous
        previous = reference(a, b), sync


def test_only_primitive_gates_and_clocked_single_bit_registers():
    raw = build_reference15()
    schematic = parse_schematic(raw)
    names = named_nets(schematic)
    counts = Counter(block.symbol for block in schematic.blocks.values())
    assert set(counts) == {"D", "AND", "OR", "XOR"}
    assert counts["D"] == 47  # Two 15-bit inputs, one 15-bit output, two SYNC stages.
    assert all(names[f"{b.id}.C"] == "CLK" for b in schematic.blocks.values() if b.symbol == "D")
    assert all(f"{b.id}.{p.name}" in names for b in schematic.blocks.values() for p in b.pins)
    assert raw == build_reference15()
    layout = make_layout(schematic)
    assert layout.blocks["RA00"].rect.right < layout.blocks["RY00"].rect.left
    assert layout.width * layout.height < 85_000_000


def test_named_nets_reject_false_connections():
    raw = {"blocks": {"A": {"outputs": ["Q"]}, "B": {"inputs": ["D"]}},
           "net_names": {"A.Q": "DATA", "B.D": "DATA"}}
    with pytest.raises(SchematicError, match="disconnected"):
        named_nets(parse_schematic(raw))
    raw["connections"] = ["A.Q -> B.D"]
    assert set(named_nets(parse_schematic(raw)).values()) == {"DATA"}
    raw["net_names"]["B.D"] = "WRONG"
    with pytest.raises(SchematicError, match="Conflicting"):
        named_nets(parse_schematic(raw))
