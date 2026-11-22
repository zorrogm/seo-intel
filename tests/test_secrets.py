import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Shapes of real keys, never placeholders
KEY_SHAPES = re.compile(r"AIza[0-9A-Za-z_-]{30,}|AQ\.[0-9A-Za-z_-]{30,}|LLM_\d{10,}_[0-9A-Za-z]{10,}")


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return out.stdout.split()


def test_env_file_is_never_tracked():
    files = tracked_files()
    assert ".env" not in files
    assert ".env.example" in files


def test_no_api_key_in_tracked_files():
    for name in tracked_files():
        path = ROOT / name
        if path.is_file() and path.stat().st_size < 2_000_000:
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert not KEY_SHAPES.search(text), name


def test_example_file_holds_no_value():
    for line in (ROOT / ".env.example").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            assert line.split("=", 1)[1].strip() == ""
