"""Gate-level implementation of the 1/4/10-bit datapath in the reference."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import yaml

from .model import parse_schematic
from .layout import make_layout
from .nets import named_nets
from .render import render_schematic


class GateBuilder:
    def __init__(self) -> None:
        self.blocks: dict[str, dict] = {}
        self.connections: list[str] = []
        self.net_names: dict[str, str] = {}
        self.drivers: dict[str, str] = {}
        self.sections: dict[str, list[str]] = {}
        self.clock_pins: list[str] = []
        self.layout_groups: dict[str, list[str]] = {}

    def connect(self, net: str, target: str) -> None:
        if net in self.drivers:
            self.connections.append(f"{self.drivers[net]} -> {target}")
        else:
            self.net_names[target] = net
            self.drivers[net] = target

    def gate(self, symbol: str, inputs: list[str], net: str, section: str) -> str:
        block_id = f"G{len(self.blocks):03d}"
        pins = ["A", "B"][:len(inputs)]
        self.blocks[block_id] = {
            "symbol": symbol, "position": [0, 0], "inputs": pins, "outputs": ["Q"]
        }
        self.sections.setdefault(section, []).append(block_id)
        for pin, source in zip(pins, inputs):
            self.connect(source, f"{block_id}.{pin}")
        ref = f"{block_id}.Q"
        self.drivers[net] = ref
        self.net_names[ref] = net
        return net

    def dff(self, block_id: str, source: str, net: str, section: str) -> str:
        self.blocks[block_id] = {
            "symbol": "D", "position": [0, 0],
            "inputs": ["D", {"name": "C", "marker": "clock"}], "outputs": ["Q"]
        }
        self.sections.setdefault(section, []).append(block_id)
        self.connect(source, f"{block_id}.D")
        self.clock_pins.append(f"{block_id}.C")
        self.drivers[net] = f"{block_id}.Q"
        self.net_names[f"{block_id}.Q"] = net
        return net

    def add(self, a: list[str | None], b: list[str | None], prefix: str, section: str) -> list[str | None]:
        result: list[str | None] = []
        carry: str | None = None
        for bit, (x, y) in enumerate(zip(a, b)):
            terms = [term for term in (x, y, carry) if term is not None]
            name = f"{prefix}_{bit:02d}"
            if len(terms) < 2:
                result.append(terms[0] if terms else None)
                carry = None
                continue
            x, y = terms[:2]
            first_gate = len(self.blocks)
            p = self.gate("XOR", [x, y], name + "p", section)
            g = self.gate("AND", [x, y], name + "g", section)
            if len(terms) == 2:
                result.append(p)
                carry = g
            else:
                z = terms[2]
                result.append(self.gate("XOR", [p, z], name + "s", section))
                h = self.gate("AND", [p, z], name + "h", section)
                carry = self.gate("OR", [g, h], name + "c", section)
            self.layout_groups[name] = list(self.blocks)[first_gate:]
        result.append(carry)
        return result

    def document(self) -> dict:
        for pin in self.clock_pins:
            self.connect("CLK", pin)
        # Each arithmetic stage occupies a column; its carry flows down the column.
        for col, block_ids in enumerate(self.sections.values()):
            for row, block_id in enumerate(block_ids):
                self.blocks[block_id]["position"] = [col, row]
        return {
            "canvas": {"wiring": "named", "scale": 1, "margin": 80, "column_gap": 44,
                       "row_gap": 32, "font_size": 16, "small_font_size": 13},
            "blocks": self.blocks, "connections": self.connections,
            "net_names": self.net_names,
            "layout_groups": self.layout_groups,
        }


def build_reference15() -> dict:
    """Preserve the screenshot's exact bit selection, including unused carries."""
    builder = GateBuilder()
    a = [builder.dff(f"RA{i:02d}", f"A{i:02d}", f"QA{i:02d}", "01_inputs") for i in range(15)]
    b = [builder.dff(f"RB{i:02d}", f"B{i:02d}", f"QB{i:02d}", "01_inputs") for i in range(15)]
    sync = builder.dff("RSYNC", "SYNC_IN", "SYNC_Q", "01_inputs")
    sign = builder.gate("XOR", [a[14], b[14]], "SIGN", "02_sign_exponent")
    exponent = builder.add(a[10:14], b[10:14], "E", "02_sign_exponent")
    partials = []
    for j in range(10):
        row: list[str | None] = [None] * 20
        for i in range(10):
            # Split the 100 independent ANDs between two columns.
            section = "03_partial_0_4" if j < 5 else "04_partial_5_9"
            row[i + j] = builder.gate("AND", [a[i], b[j]], f"P{j}{i}", section)
        partials.append(row)
    product = partials[0]
    for j in range(1, 10):
        product = builder.add(product, partials[j], f"M{j}", f"{j + 4:02d}_multiply_{j}")[:20]
    outputs = product[10:20] + exponent[:4] + [sign]
    for i, net in enumerate(outputs):
        assert net is not None
        builder.dff(f"RY{i:02d}", net, f"Y{i:02d}", "14_outputs")
    builder.dff("YSYNC", sync, "SYNC_OUT", "14_outputs")
    raw = builder.document()
    raw["design"] = {
        "name": "reference15", "word_bits": 15, "sync_bits": 1,
        "format": {"mantissa": [0, 9], "exponent": [10, 13], "sign": 14},
        "product_bits": [10, 19], "exponent_carry": "discarded",
        "normalization": False, "bias_correction": False,
        "clock": "CLK rising edge; all D flip-flops share the same clock",
        "latency": "capture inputs at edge n, output data and SYNC at edge n+1",
        "startup": "No reset in reference; ignore output until a captured SYNC_IN=1 arrives.",
        "sections": builder.sections,
        "counts": dict(Counter(block["symbol"] for block in builder.blocks.values())),
    }
    return raw


def write_reference15(output_dir: str | Path) -> dict:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    raw = build_reference15()
    raw["primitives"] = _sheet_titles(raw, "REFERENCE 15 / 538 GATES + 47 D FLIP-FLOPS / DATA 15 + SYNC 1",
                                      raw["design"]["sections"])
    (destination / "reference15.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    render_schematic(parse_schematic(raw), destination / "reference15.png")
    # Full-size stage sheets retain the exact global net names for cross-reference.
    all_names = named_nets(parse_schematic(raw))
    for section, block_ids in raw["design"]["sections"].items():
        refs = set(block_ids)
        page = {
            "canvas": raw["canvas"],
            "blocks": {bid: dict(raw["blocks"][bid], position=[idx // 18, idx % 18])
                       for idx, bid in enumerate(block_ids)},
            "net_names": {ref: name for ref, name in all_names.items() if ref.split(".")[0] in refs},
        }
        # Reconstruct each net's local fanout, including nets driven on other sheets.
        nets: dict[str, list[str]] = {}
        for ref, name in page["net_names"].items():
            nets.setdefault(name, []).append(ref)
        page["connections"] = [" -> ".join(pins) for pins in nets.values() if len(pins) > 1]
        page["primitives"] = _sheet_titles(page, section.upper().replace("_", " "), {})
        render_schematic(parse_schematic(page), destination / f"{section}.png")
    return raw


def _sheet_titles(raw: dict, title: str, sections: dict) -> list[dict]:
    layout = make_layout(parse_schematic(raw))
    headings = [
        {"type": "text", "position": [24, 12], "text": title, "font_size": 14},
        {"type": "text", "position": [24, 34],
         "text": "Equal net names are connected. CLK: rising edge.", "font_size": 12},
    ]
    for section, ids in sections.items():
        x = layout.blocks[ids[0]].rect.left - 20
        headings.append({"type": "text", "position": [x, 60],
                         "text": section.upper().replace("_", " "), "font_size": 14})
    return headings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the reference 15-bit gate-level datapath with SYNC.")
    parser.add_argument("--output-dir", default="output/reference15")
    args = parser.parse_args(argv)
    raw = write_reference15(args.output_dir)
    print(f"Generated {len(raw['blocks'])} blocks in {args.output_dir}")
    print("Symbols: " + ", ".join(f"{key}={value}" for key, value in raw["design"]["counts"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
