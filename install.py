"""Install the checkout into a local virtual environment without global changes."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parent


def venv_python(folder: Path) -> Path:
    return folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def install_commands(python: Path, *, layout: bool, dev: bool) -> list[list[str]]:
    extras = [name for name, enabled in (("layout", layout), ("test", dev)) if enabled]
    target = ".[" + ",".join(extras) + "]" if extras else "."
    commands = [[str(python), "-m", "pip", "install", "-e", target]]
    if layout:
        commands.append([str(python), "-c",
                         "from nodejs_wheel import npm; "
                         "raise SystemExit(npm(['ci', '--ignore-scripts', '--no-audit', '--no-fund']))"])
    commands.append([str(python), "-c",
                     "from schematic_renderer.model import load_schematic; "
                     "from schematic_renderer.layout import make_layout; "
                     "make_layout(load_schematic('examples/simple.yaml')); "
                     "print('Renderer import and example validation: OK')"])
    if layout:
        commands.append([str(python), "-c",
                         "from schematic_renderer.prepare import prepare_connected; "
                         "from schematic_renderer.model import parse_schematic; "
                         "from schematic_renderer.layout import make_layout; "
                         "from schematic_renderer.connected import connected_routes; "
                         "s=parse_schematic(prepare_connected({'blocks': "
                         "{'A': {'outputs':['Q']}, 'B': {'inputs':['D']}}, "
                         "'connections':['A.Q -> B.D']})); "
                         "connected_routes(s, make_layout(s)); print('ELK routing: OK')"])
    return commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", action="store_true", help="Install local Node.js and ELK for automatic routing.")
    parser.add_argument("--dev", action="store_true", help="Also install pytest for development.")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.", file=sys.stderr)
        return 1
    folder = ROOT / ".venv"
    try:
        if folder.is_symlink() or folder.resolve() != folder.absolute():
            raise RuntimeError("Refusing a redirected .venv directory.")
        if folder.exists() and not (folder / "pyvenv.cfg").is_file():
            raise RuntimeError(".venv exists but is not a virtual environment; nothing was removed.")
        if not folder.exists():
            print("Creating .venv ...", flush=True)
            venv.EnvBuilder(with_pip=True).create(folder)
        python = venv_python(folder)
        if not python.is_file():
            raise RuntimeError(".venv has no Python interpreter. Rename it and run the installer again.")
        env = os.environ.copy()
        env["PIP_REQUIRE_VIRTUALENV"] = "true"
        for key in ("PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PYTHONHOME"):
            env.pop(key, None)
        for command in install_commands(python, layout=args.layout, dev=args.dev):
            print("Running: " + subprocess.list2cmdline(command), flush=True)
            subprocess.run(command, cwd=ROOT, env=env, check=True)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        print("Check your network and Python/venv installation, then rerun install.py.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInstallation interrupted; rerun install.py to continue.", file=sys.stderr)
        return 130
    print("\nInstalled. Run from the project directory:")
    command_python = r".venv\Scripts\python.exe" if os.name == "nt" else ".venv/bin/python"
    print(f"  {command_python} -m schematic_renderer examples/simple.yaml -o output/simple.png")
    if args.dev:
        print(f"  {command_python} -m pytest -q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
