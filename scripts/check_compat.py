"""Fail the build if the codebase uses anything newer than Python 3.13.

Why this exists: the project is developed on Python 3.14 locally but runs on
Python 3.13 on the host. A 3.14-only feature (t-strings, `compression.zstd`, new
annotation semantics) would pass every local test and then fail to import in
production. This check is the guardrail, run before each deploy.

    python scripts/check_compat.py
    echo $LASTEXITCODE      # 0 = compatible, 1 = too new

Requires the dev dependency:  pip install -r requirements-dev.txt
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TARGET = (3, 13)
ROOT = Path(__file__).resolve().parent.parent

# vermin.main reads sys.argv[1:], which becomes the flags after `-c`.
COMMAND = [
    sys.executable,
    "-c",
    "from vermin.main import main; main()",
    f"-t={TARGET[0]}.{TARGET[1]}",
    "--no-tips",
    "--exclude",
    ".venv,staticfiles,.git,node_modules",
    ".",
]


def parse_minimum(output: str) -> tuple[int, int] | None:
    """Extract the highest Python version vermin says the code requires."""
    match = re.search(r"Minimum required versions:\s*(.+)", output)
    if not match:
        return None
    versions = re.findall(r"(?<![\d.])(\d+)\.(\d+)(?![\d.])", match.group(1))
    if not versions:
        # e.g. "3" with no minor - treat as (3, 0)
        major = re.search(r"(\d+)", match.group(1))
        return (int(major.group(1)), 0) if major else None
    return max((int(major), int(minor)) for major, minor in versions)


def main() -> int:
    try:
        result = subprocess.run(
            COMMAND, cwd=ROOT, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        print("vermin is not installed. Run: pip install -r requirements-dev.txt")
        return 2

    output = f"{result.stdout}\n{result.stderr}"
    minimum = parse_minimum(output)

    if minimum is None:
        print("Could not determine required Python version. Raw vermin output:")
        print(output[-2000:])
        return 2

    required = f"{minimum[0]}.{minimum[1]}"
    target = f"{TARGET[0]}.{TARGET[1]}"

    if minimum > TARGET:
        print(f"FAIL: code requires Python {required}, but the host runs {target}.")
        print("Find the offending construct with:")
        print(f"  python -c \"from vermin.main import main; main()\" -t={target} --no-tips -vv .")
        return 1

    print(f"OK: code requires Python {required}; host runs {target}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
