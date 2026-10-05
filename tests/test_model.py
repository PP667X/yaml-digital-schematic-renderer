import pytest

from schematic_renderer.errors import SchematicError
from schematic_renderer.model import parse_schematic


def test_range_expands_to_numbered_pins():
    schematic = parse_schematic({
        "blocks": {"B1": {"symbol": "RG", "position": [0, 0], "inputs": ["A[0:2]"]}},
    })
    assert [pin.name for pin in schematic.blocks["B1"].inputs] == ["A0", "A1", "A2"]


def test_unknown_pin_is_reported():
    with pytest.raises(SchematicError, match="Unknown pin"):
        parse_schematic({
            "blocks": {"B1": {"symbol": "X", "position": [0, 0], "inputs": ["A"]}},
            "ports": {"IN": {"direction": "input", "position": [0, 0]}},
            "connections": ["IN -> B1.NOPE"],
        })


def test_ambiguous_block_reference_is_reported():
    with pytest.raises(SchematicError, match="Ambiguous reference"):
        parse_schematic({
            "blocks": {"B1": {"symbol": "X", "position": [0, 0], "inputs": ["A"], "outputs": ["Q"]}},
            "ports": {"OUT": {"direction": "output", "position": [1, 0]}},
            "connections": ["B1 -> OUT"],
        })
