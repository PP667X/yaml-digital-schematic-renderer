import random

from schematic_renderer.assignment15 import build_assignment15
from schematic_renderer.model import parse_schematic
from schematic_renderer.nets import named_nets


class GateMachine:
    def __init__(self):
        self.raw = build_assignment15()
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
        return (sum(self.state[f"Y{i:02d}"] << i for i in range(15)),
                self.state["RANGE_ERR"], self.state["SYNC_OUT"])


def encode(fraction, exponent, sign):
    return fraction | (sign << 9) | ((exponent & 31) << 10)


def reference(a, b, sync):
    fraction_a, fraction_b = a & 511, b & 511
    if not fraction_a or not fraction_b:
        return 0, 0, sync
    ea, eb = a >> 10, b >> 10
    ea = ea - 32 if ea & 16 else ea
    eb = eb - 32 if eb & 16 else eb
    product = fraction_a * fraction_b
    shift = int(product < 131072)
    exponent = ea + eb - shift
    word = encode(product >> (9-shift), exponent, ((a ^ b) >> 9) & 1)
    return word, int(not -16 <= exponent <= 15), sync


def test_signed_normalized_multiply_range_and_sync():
    machine = GateMachine()
    rng = random.Random(15)
    vectors = [(encode(ma, ea, sa), encode(mb, eb, sb), (ea + eb) & 1)
               for ma, mb in ((0, 511), (256, 256), (511, 511), (362, 362), (363, 363))
               for ea in (-16, -15, -1, 0, 1, 14, 15)
               for eb in (-16, -15, -1, 0, 1, 14, 15)
               for sa, sb in ((0, 0), (0, 1), (1, 0), (1, 1))]
    vectors += [(encode(rng.randrange(256, 512), rng.randrange(-16, 16), rng.randrange(2)),
                 encode(rng.randrange(256, 512), rng.randrange(-16, 16), rng.randrange(2)),
                 rng.randrange(2)) for _ in range(1000)]
    expected = (0, 0, 0)
    for a, b, sync in vectors + [(0, 0, 0)]:
        assert machine.edge(a, b, sync) == expected
        expected = reference(a, b, sync)


def test_assignment_structure():
    machine = GateMachine()
    assert len(machine.registers) == 48
    assert set(b.symbol for b in machine.model.blocks.values()) == {"CLK", "D", "AND", "OR", "NOT", "XOR"}
    names = named_nets(machine.model)
    assert all(names[f"{b.id}.C"] == "CLK" for b in machine.model.blocks.values() if b.symbol == "D")
