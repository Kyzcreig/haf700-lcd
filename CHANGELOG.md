# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow [SemVer](https://semver.org/).

## [1.0.0] - 2026-06-18

First tagged release. The Linux control path for the Cooler Master HAF 700 EVO LCD has been
eye-confirmed working (image / GIF / video display + screenshot) — the first public Linux tooling
for this panel.

### Added
- `haf700-lcd info | show | screenshot | restore` CLI.
- `--version` flag and `__version__` (1.0.0).
- Hardware-free test suite (`test_haf700_lcd.py`, 12 tests): `currentType` codec round-trip + header
  inheritance + garbage-input fallback, the ffmpeg cover/contain "no black bars" filter contract,
  version wiring, and CLI entry-point smoke tests that actually launch the script.
- GitHub Actions CI (`.github/workflows/smoke.yml`) running the suite on Python 3.9/3.11/3.12.

### Changed
- Refactored the `currentType` logic into pure, testable helpers
  (`parse_filename_from_hex`, `build_current_type`) split from the device-reading wrappers, so the
  byte-level codec can be tested without a panel. Behavior is unchanged.
- Narrowed a bare `except Exception` in the codec to `(ValueError, UnicodeDecodeError)`.
