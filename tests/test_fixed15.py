from collections import Counter
import random

from schematic_renderer.fixed15 import build_fixed15
from schematic_renderer.model import parse_schematic
from schematic_renderer.nets import named_nets


class FixedMachine:
    """Simulate the actual exported gate connections and simultaneous D capture."""
    def __init__(self):
        self.raw = build_fixed15()
        self.model = parse_schematic(self.raw)
        names = named_nets(self.model)
        self.registers = [(names[f"{b.id}.D"], names[f"{b.id}.Q"])
                          for b in self.model.blocks.values() if b.symbol == "D"]
        self.gates = [(b.symbol, [names[f"{b.id}.{p.name}"] for p in b.inputs], names[f"{b.id}.Q"])
                      for b in self.model.blocks.values() if b.symbol not in {"D", "CLK"}]
        self.state = {q: 0 for _, q in self.registers}

    def edge(self, a, b, sync):
        values = {f"{prefix}{i:02d}": (word >> i) & 1
                  for prefix, word in (("A", a), ("B", b)) for i in range(15)}
        values.update(self.state)
        values["SYNC_IN"] = sync
        for symbol, inputs, output in self.gates:
            x = values[inputs[0]]
            if symbol == "NOT":
                values[output] = 1 - x
            else:
                y = values[inputs[1]]
                values[output] = {"AND": x & y, "OR": x | y, "XOR": x ^ y}[symbol]
        self.state = {q: values[d] for d, q in self.registers}
        code = sum(self.state[f"Y{i:02d}"] << i for i in range(30))
        return code - (1 << 30) if code & (1 << 29) else code, self.state["SYNC_OUT"]


def test_full_signed_product_and_sync():
    machine = FixedMachine()
    limits = [-16384, -16383, -8192, -33, -32, -31, -1, 0, 1, 31, 32, 33, 8191, 16382, 16383]
    vectors = [(a, b, (a + b) & 1) for a in limits for b in limits]
    rng = random.Random(1505)
    vectors += [(rng.randrange(-16384, 16384), rng.randrange(-16384, 16384), rng.randrange(2))
                for _ in range(2000)]
    # Fractional examples: 1.5 * -2.25 = -3.375; one LSB squared = 1/1024.
    vectors += [(48, -72, 1), (1, 1, 1), (-16384, -16384, 1), (-16384, 16383, 1)]
    expected = (0, 0)
    for a, b, sync in vectors + [(0, 0, 0)]:
        assert machine.edge(a, b, sync) == expected
        expected = a * b, sync


def test_fixed_point_structure_has_no_exponent_logic():
    machine = FixedMachine()
    raw = machine.raw
    names = named_nets(machine.model)
    assert len(machine.registers) == 62
    assert {b.symbol for b in machine.model.blocks.values()} == {"D", "CLK", "AND", "OR", "XOR", "NOT"}
    assert raw["design"]["operand_fraction_bits"] == 5
    assert raw["design"]["result_fraction_bits"] == 10
    assert all(names[f"{b.id}.C"] == "CLK" for b in machine.model.blocks.values() if b.symbol == "D")
    drivers = Counter(ref.split(".")[0] for ref in raw["net_names"] if ref.endswith(".Q"))
    assert set(drivers) == set(raw["blocks"])
    assert all(count == 1 for count in drivers.values())
    members = [bid for group in raw["layout_groups"].values() for bid in group]
    assert len(members) == len(set(members))
    assert raw == build_fixed15()
