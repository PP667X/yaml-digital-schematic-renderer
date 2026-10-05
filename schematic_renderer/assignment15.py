"""Signed normalized 10-bit mantissa / signed 5-bit exponent multiplier."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import yaml
from PIL import Image

from .generate import GateBuilder
from .model import load_schematic
from .layout import make_layout
from .prepare import prepare_connected
from .render import render_schematic


def build_assignment15() -> dict:
    b = GateBuilder()
    b.blocks["CLOCK"] = {"symbol": "CLK", "position": [0, 0], "outputs": ["Q"]}
    b.sections["00_clock"] = ["CLOCK"]
    b.drivers["CLK"] = "CLOCK.Q"
    b.net_names["CLOCK.Q"] = "CLK"
    a = [b.dff(f"RA{i:02d}", f"A{i:02d}", f"QA{i:02d}", "01_input_registers") for i in range(15)]
    d = [b.dff(f"RB{i:02d}", f"B{i:02d}", f"QB{i:02d}", "01_input_registers") for i in range(15)]
    sync = b.dff("RSYNC", "SYNC_IN", "SYNC_Q", "01_input_registers")
    for name in [f"RA{i:02d}" for i in range(15)] + [f"RB{i:02d}" for i in range(15)] + ["RSYNC"]:
        b.blocks[name]["inputs"][0] = {"name": "D", "label": b.net_names[f"{name}.D"]}

    rows = []
    for j in range(9):
        row = [None] * 18
        for i in range(9):
            row[i + j] = b.gate("AND", [a[i], d[j]], f"P{j}{i}", "02_partial_products")
        rows.append(row)
    product = rows[0]
    for j in range(1, 9):
        product = b.add(product, rows[j], f"M{j}", f"03_product_row_{j}")[:18]
    assert all(product)

    section = "04_normalization"
    high = product[17]
    shift = b.gate("NOT", [high], "SHIFT", section)
    mantissa = []
    for i in range(9):
        left = b.gate("AND", [product[i + 8], shift], f"NL{i}", section)
        right = b.gate("AND", [product[i + 9], high], f"NR{i}", section)
        mantissa.append(b.gate("OR", [left, right], f"NM{i}", section))

    section = "05_exponent"
    # Seven bits are needed for -16 + -16 - 1 = -33 before range checking.
    exponent = b.add(a[10:15] + [a[14]] * 2, d[10:15] + [d[14]] * 2, "ES", section)[:7]
    exponent = b.add(exponent, [shift] * 7, "EC", section)[:7]
    ov1 = b.gate("XOR", [exponent[4], exponent[5]], "OV1", section)
    ov2 = b.gate("XOR", [exponent[5], exponent[6]], "OV2", section)
    overflow = b.gate("OR", [ov1, ov2], "ERANGE_RAW", section)

    section = "06_sign_zero"
    sign = b.gate("XOR", [a[9], d[9]], "SIGN_RAW", section)
    nonzero = []
    for prefix, bits in (("A", a[:9]), ("B", d[:9])):
        net = bits[0]
        for i, bit in enumerate(bits[1:], 1):
            net = b.gate("OR", [net, bit], f"{prefix}NZ{i}", section)
        nonzero.append(net)
    nz = b.gate("AND", nonzero, "NONZERO", section)
    outputs = mantissa + [sign] + exponent[:5]
    for i, net in enumerate(outputs):
        cleaned = b.gate("AND", [net, nz], f"RESULT{i:02d}", "07_zero_mask")
        b.dff(f"RY{i:02d}", cleaned, f"Y{i:02d}", "08_output_registers")
        b.blocks[f"RY{i:02d}"]["outputs"] = [{"name": "Q", "label": f"Y{i:02d}"}]
    error = b.gate("AND", [overflow, nz], "ERANGE", "07_zero_mask")
    b.dff("RERR", error, "RANGE_ERR", "08_output_registers")
    b.dff("YSYNC", sync, "SYNC_OUT", "08_output_registers")
    for block_id, label in (("RERR", "RANGE_ERR"), ("YSYNC", "SYNC_OUT")):
        b.blocks[block_id]["outputs"] = [{"name": "Q", "label": label}]
    raw = b.document()
    raw["canvas"].update(wiring="routed", font_size=24, small_font_size=20,
                         pin_length=24, block_padding_x=20, min_block_width=180,
                         min_block_height=104, pin_gap=32, block_padding_y=24)
    raw["design"] = {
        "name": "assignment15", "word_bits": 15, "sync_bits": 1,
        "encoding": {"fraction": [0, 8], "mantissa_sign": 9,
                     "exponent_twos_complement": [10, 14]},
        "value": "(-1)^bit9 * unsigned(bits0..8)/512 * 2^signed(bits10..14)",
        "input_requirement": "fraction = 0 or 256..511 (normalized inputs)",
        "normalization": "P = fracA * fracB; shift = NOT P17; fracY = P >> (9-shift)",
        "exponent": "signed(EA) + signed(EB) - shift, computed with 7 bits",
        "rounding": "truncate toward zero to 9 fraction bits",
        "zero": "zero operand gives canonical all-zero output and RANGE_ERR=0",
        "range_error": "RANGE_ERR=1 when a nonzero result exponent is outside -16..15; Y then invalid",
        "clock": "CLK rising edge, shared by all D flip-flops",
        "latency": "capture A/B/SYNC_IN at edge n, Y/RANGE_ERR/SYNC_OUT at edge n+1",
        "startup": "No reset; ignore outputs until the first SYNC_OUT=1",
        "sections": b.sections,
        "counts": dict(Counter(block["symbol"] for block in b.blocks.values())),
    }
    return {"design": raw.pop("design"), **raw}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate and render a fully wired 15-bit floating-point multiplier.")
    parser.add_argument("--output-dir", default="output/assignment15")
    parser.add_argument("--preview", action="store_true", help="Also create a separate reduced overview.png.")
    args = parser.parse_args(argv)
    folder = Path(args.output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    raw = build_assignment15()
    source = folder / "assignment15.logic.yaml"
    source.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    print(f"Logic YAML: {len(raw['blocks'])} blocks, {len(raw['connections'])} connections", flush=True)
    # Read the saved source, then save the prepared geometry before rendering it.
    prepared = prepare_connected(yaml.safe_load(source.read_text(encoding="utf-8")))
    prepared["primitives"] = [
        {"type": "text", "position": [80, 16], "font_size": 22,
         "text": "SIGNED FLOATING-POINT MULTIPLIER / M10 (SIGN + FRACTION9) / E5 / DATA15 + SYNC"},
        {"type": "text", "position": [80, 48], "font_size": 16,
         "text": "Dot = electrical junction. Arc = crossing without contact. All registers share CLK. RANGE_ERR = invalid result."},
    ]
    path = folder / "assignment15.yaml"
    path.write_text(yaml.safe_dump(prepared, sort_keys=False), encoding="utf-8")
    schematic = load_schematic(path)
    layout = make_layout(schematic)
    print(f"Prepared YAML: {layout.width} x {layout.height}; no fit-to-page scaling", flush=True)
    render_schematic(schematic, folder / "assignment15.png")
    render_schematic(schematic, folder / "assignment15.svg")
    # This image is generated locally; use its known dimensions for the preview.
    if args.preview:
        limit = Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS = max(limit or 0, layout.width * layout.height * schematic.canvas.scale ** 2)
            with Image.open(folder / "assignment15.png") as picture:
                picture.thumbnail((1800, 1800))
                picture.save(folder / "overview.png")
        finally:
            Image.MAX_IMAGE_PIXELS = limit
    print(f"Rendered {folder / 'assignment15.png'}", flush=True)


if __name__ == "__main__":
    main()
