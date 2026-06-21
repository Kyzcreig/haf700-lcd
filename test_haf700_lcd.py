"""Hardware-free smoke + unit tests for haf700-lcd.

These cover the parts that don't need a physical panel: the currentType
(magic.xml) codec, the ffmpeg "no black bars" filter contract, version
wiring, and that the CLI actually parses/launches (the entry-point smoke
test that catches a broken argparse or import).

Run: python -m pytest -v
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
CLI = HERE / "haf700_lcd.py"

# Import the CLI module directly (it's a single-file script, not a package).
spec = importlib.util.spec_from_file_location("haf700_lcd", CLI)
haf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(haf)


# --- currentType codec: parse_filename_from_hex ---------------------------

def test_parse_filename_from_real_masterplus_value():
    # The real currentType captured from Ace's panel (see PROTOCOL.md).
    cur = "128000010026110000000000000000000001FFFFFFFF0003FF000000000E313739393939303030312E6D7034"
    assert haf.parse_filename_from_hex(cur) == "1799990001.mp4"


def test_parse_filename_none_and_garbage():
    assert haf.parse_filename_from_hex(None) is None
    assert haf.parse_filename_from_hex("") is None
    # valid hex but no .mp4 tail
    assert haf.parse_filename_from_hex("1280000100") is None
    # odd-length / non-hex must not raise
    assert haf.parse_filename_from_hex("zzz") is None
    assert haf.parse_filename_from_hex("abc") is None


# --- currentType codec: build_current_type --------------------------------

def test_build_round_trips_filename():
    out = haf.build_current_type(None, "1799990002.mp4")
    assert haf.parse_filename_from_hex(out) == "1799990002.mp4"


def test_build_inherits_existing_header():
    cur = "128000010026110000000000000000000001FFFFFFFF0003FF000000000E313739393939303030312E6D7034"
    header_only = bytes.fromhex(cur)[:-(1 + len("1799990001.mp4"))]
    out = haf.build_current_type(cur, "1799990099.mp4")
    # New filename swapped in...
    assert haf.parse_filename_from_hex(out) == "1799990099.mp4"
    # ...and the config header preserved byte-for-byte.
    assert bytes.fromhex(out).startswith(header_only)


def test_build_falls_back_to_default_header_on_garbage():
    out = haf.build_current_type("not-hex!!", "1799990003.mp4")
    assert bytes.fromhex(out).startswith(bytes.fromhex(haf.DEFAULT_HEADER_HEX))
    assert haf.parse_filename_from_hex(out) == "1799990003.mp4"


def test_build_namelen_byte_is_correct():
    name = "1799990004.mp4"
    out = bytes.fromhex(haf.build_current_type(None, name))
    # byte immediately before the ascii name == len(name)
    assert out[-(1 + len(name))] == len(name)


# --- ffmpeg "no black bars" filter contract -------------------------------

def test_cover_filter_crops_not_pads():
    vf = haf.build_vf("cover")
    assert "crop=480:480" in vf
    assert "increase" in vf       # scale to cover
    assert "pad=" not in vf        # cover must NEVER add bars


def test_contain_filter_pads():
    vf = haf.build_vf("contain")
    assert "pad=480:480" in vf


# --- version wiring -------------------------------------------------------

def test_version_constant_present():
    assert haf.__version__
    assert all(part.isdigit() for part in haf.__version__.split("."))


# --- CLI entry-point smoke tests (actually run the script) ----------------

def test_cli_version_runs():
    r = subprocess.run([sys.executable, str(CLI), "--version"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    assert haf.__version__ in r.stdout


def test_cli_help_runs():
    r = subprocess.run([sys.executable, str(CLI), "--help"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    assert "haf700-lcd" in r.stdout
    for sub in ("info", "show", "screenshot", "restore"):
        assert sub in r.stdout


def test_cli_no_args_is_error_not_crash():
    # required subparser -> argparse exits 2, not a traceback
    r = subprocess.run([sys.executable, str(CLI)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
