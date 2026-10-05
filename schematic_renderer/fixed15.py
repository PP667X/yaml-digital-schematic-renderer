"""Signed 15-bit fixed-point multiplier with an exact 30-bit result."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import yaml

from .generate import GateBuilder
from .layout import make_layout
from .model import load_schematic
from .prepare import prepare_connected
from .render import render_schematic


def build_fixed15() -> dict:
    b = GateBuilder()
    b.blocks["CLOCK"] = {"symbol": "CLK", "position": [0, 0], "outputs": ["Q"]}
    b.sections["00_clock"] = ["CLOCK"]
    b.drivers["CLK"] = "CLOCK.Q"
    b.net_names["CLOCK.Q"] = "CLK"
    a = [b.dff(f"RA{i:02d}", f"A{i:02d}", f"QA{i:02d}", "01_input_registers") for i in range(15)]
    d = [b.dff(f"RB{i:02d}", f"B{i:02d}", f"QB{i:02d}", "01_input_registers") for i in range(15)]
    sync = b.dff("RSYNC", "SYNC_IN", "SYNC_Q", "01_input_registers")
    for name in b.sections["01_input_registers"]:
        b.blocks[name]["inputs"][0] = {"name": "D", "label": b.net_names[f"{name}.D"]}

    inverse = b.gate("NOT", [a[0]], "NOT_A0", "02_signed_correction")
    one = b.gate("OR", [a[0], inverse], "ONE", "02_signed_correction")
    rows = []
    for j in range(15):
        row: list[str | None] = [None] * 30
        for i in range(15):
            term = b.gate("AND", [a[i], d[j]], f"P{j:02d}_{i:02d}", "03_partial_products")
            # A sign bit contributes a negative weight, except sign * sign.
            if (i == 14) != (j == 14):
                term = b.gate("NOT", [term], f"N{j:02d}_{i:02d}", "03_partial_products")
            row[i + j] = term
        rows.append(row)
    # Complementing the 28 negative terms requires +2^15 +2^29 modulo 2^30.
    # These unused positions in row zero avoid a separate correction adder.
    rows[0][15], rows[0][29] = one, one
    product = rows[0]
    for j in range(1, 15):
        product = b.add(product, rows[j], f"M{j}", f"04_product_row_{j:02d}")[:30]
    assert all(product)
    for i, net in enumerate(product):
        b.dff(f"RY{i:02d}", net, f"Y{i:02d}", "05_output_registers")
        b.blocks[f"RY{i:02d}"]["outputs"] = [{"name": "Q", "label": f"Y{i:02d}"}]
    b.dff("YSYNC", sync, "SYNC_OUT", "05_output_registers")
    b.blocks["YSYNC"]["outputs"] = [{"name": "Q", "label": "SYNC_OUT"}]
    raw = b.document()
    raw["canvas"].update(wiring="routed", font_size=24, small_font_size=20,
                         pin_length=24, block_padding_x=20, min_block_width=180,
                         min_block_height=104, pin_gap=32, block_padding_y=24)
    design = {
        "name": "fixed15", "operation": "signed fixed-point multiplication",
        "operand_bits": 15, "operand_fraction_bits": 5,
        "result_bits": 30, "result_fraction_bits": 10,
        "encoding": "two's complement on both inputs and output",
        "input_value": "signed15(A[14:0]) / 32; signed15(B[14:0]) / 32",
        "output_value": "signed30(Y[29:0]) / 1024 = input_A * input_B",
        "input_range": "-512 .. 511.96875, step 1/32",
        "product_code_range": "-268419072 .. 268435456; fits signed 30 bits",
        "arithmetic": "Baugh-Wooley partial products; invert terms with exactly one sign bit; add 2^15 + 2^29 modulo 2^30",
        "rounding": "none; all 30 product bits are retained",
        "overflow": "none for legal input words; no saturation or discarded fractional bits",
        "clock": "all 62 D flip-flops share the rising edge of CLK",
        "sync": "one additional validity bit, independent of the arithmetic data",
        "latency": "capture A/B/SYNC_IN at edge n; Y/SYNC_OUT at edge n+1",
        "startup": "No reset; ignore outputs until the first SYNC_OUT=1",
        "sections": b.sections,
        "counts": dict(Counter(block["symbol"] for block in b.blocks.values())),
    }
    return {"design": design, **raw}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate a signed 15-bit fixed-point multiplier (5 fractional bits).")
    parser.add_argument("--output-dir", default="output/fixed15")
    args = parser.parse_args(argv)
    folder = Path(args.output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "fixed15.logic.yaml"
    raw = build_fixed15()
    source.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    print(f"Logic YAML: {len(raw['blocks'])} blocks, {len(raw['connections'])} connections", flush=True)
    prepared = prepare_connected(yaml.safe_load(source.read_text(encoding="utf-8")))
    prepared["primitives"] = [
        {"type": "text", "position": [80, 16], "font_size": 22,
         "text": "SIGNED FIXED-POINT MULTIPLIER / INPUTS: 15 BITS, FRACTION 5 / OUTPUT: 30 BITS, FRACTION 10 / SYNC"},
        {"type": "text", "position": [80, 48], "font_size": 16,
         "text": "Two's complement. Exact full product. Dot = junction; arc = crossing without contact. Common rising-edge CLK."},
    ]
    path = folder / "fixed15.yaml"
    path.write_text(yaml.safe_dump(prepared, sort_keys=False), encoding="utf-8")
    schematic = load_schematic(path)
    layout = make_layout(schematic)
    print(f"Prepared YAML: {layout.width} x {layout.height}; no fit-to-page scaling", flush=True)
    render_schematic(schematic, folder / "fixed15.svg")
    render_schematic(schematic, folder / "fixed15.png")
    print(f"Rendered {folder / 'fixed15.png'} and {folder / 'fixed15.svg'}", flush=True)


if __name__ == "__main__":
    main()
