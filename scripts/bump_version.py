#!/usr/bin/env python3
"""Bump the version in pyproject.toml. Standard library only, no install needed.

    python3 scripts/bump_version.py patch     # 0.1.0 -> 0.1.1
    python3 scripts/bump_version.py minor     # 0.1.1 -> 0.2.0
    python3 scripts/bump_version.py major     # 0.2.0 -> 1.0.0
    python3 scripts/bump_version.py 0.4.0     # set it exactly

Run it on develop before opening the promote PR into main; the release workflow
publishes whatever version main carries, and refuses to republish a tagged one.
"""

import re
import sys
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
# The version line inside [project], not a dependency's version specifier.
LINE = re.compile(r'^(version\s*=\s*")([^"]+)(")$', re.MULTILINE)


def bump(current, part):
    m = SEMVER.match(current)
    if not m:
        sys.exit(f"ERROR: current version {current!r} is not MAJOR.MINOR.PATCH")
    major, minor, patch = (int(g) for g in m.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if SEMVER.match(part):
        return part
    sys.exit(f"ERROR: expected major, minor, patch or an exact X.Y.Z version, got {part!r}")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if not PYPROJECT.exists():
        sys.exit(f"ERROR: {PYPROJECT} does not exist yet (created by issue #2)")

    text = PYPROJECT.read_text()
    match = LINE.search(text)
    if not match:
        sys.exit("ERROR: no `version = \"...\"` line found in pyproject.toml")

    current = match.group(2)
    new = bump(current, sys.argv[1])
    PYPROJECT.write_text(text[: match.start()] + f'{match.group(1)}{new}{match.group(3)}' + text[match.end():])
    print(f"{current} -> {new}")


if __name__ == "__main__":
    main()
