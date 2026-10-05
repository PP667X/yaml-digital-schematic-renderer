from pathlib import Path
import re

import yaml

from schematic_renderer.model import parse_schematic
from schematic_renderer.render import render_schematic


ROOT = Path(__file__).resolve().parents[1]


def test_documented_small_yaml_example_renders(tmp_path):
    guide = (ROOT / "docs/yaml-format.md").read_text(encoding="utf-8")
    # The first snippet is the root schema, the second is the complete example.
    sample = re.findall(r"```yaml\n(.*?)\n```", guide, re.S)[1]
    output = tmp_path / "documented.png"
    render_schematic(parse_schematic(yaml.safe_load(sample)), output)
    assert output.is_file()


def test_project_documentation_links_exist():
    files = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").glob("*.md"))]
    for document in files:
        for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("#"):
                continue
            assert (document.parent / target.split("#")[0]).exists(), (document, target)
