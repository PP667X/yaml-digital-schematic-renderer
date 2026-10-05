from __future__ import annotations

from .errors import SchematicError
from .model import Schematic, resolve_ref


def named_nets(schematic: Schematic) -> dict[str, str]:
    """Resolve labels from electrical connectivity, including chained branches."""
    parent: dict[str, str] = {}

    def canonical(ref: str) -> str:
        owner, pin = resolve_ref(ref, schematic)
        return f"{owner}.{pin}" if pin is not None else owner

    def find(ref: str) -> str:
        parent.setdefault(ref, ref)
        if parent[ref] != ref:
            parent[ref] = find(parent[ref])
        return parent[ref]

    for connection in schematic.connections:
        first = canonical(connection.chain[0])
        for ref in connection.chain[1:]:
            parent[find(canonical(ref))] = find(first)
    for ref in schematic.net_names:
        find(canonical(ref))
    labels: dict[str, str] = {}
    owners: dict[str, str] = {}
    for ref, label in schematic.net_names.items():
        root = find(canonical(ref))
        if root in labels and labels[root] != label:
            raise SchematicError(f"Conflicting names on net {ref}: {labels[root]} / {label}.")
        if label in owners and owners[label] != root:
            raise SchematicError(f"Net name {label} is used for disconnected nets.")
        labels[root] = label
        owners[label] = root
    return {ref: labels.get(find(ref), find(ref)) for ref in parent}
