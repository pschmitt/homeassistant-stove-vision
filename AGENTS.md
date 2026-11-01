# Agent instructions

## Project

This Home Assistant integration reads a stove's camera image to report displayed zone levels, residual heat, occupancy, and timer values.

## Working in this repository

- Read `README.md` before changing image decoding or camera calibration; keep the limits of supported and untested displays clear.
- Use and extend the fixture-based tests when changing decoding, calibration, or occupancy behavior.
- Before changing CI, check [pschmitt/ci-workflows](https://github.com/pschmitt/ci-workflows) for reusable components and preserve this repository's existing checks.

## Validation

- Run `uv run --python 3.14 --with pytest --with pillow --with "homeassistant==2026.9.4" pytest tests/` for the test suite.
- Run `uvx ruff check .` and `uvx ruff format --check .` for Python changes; CI also runs Hassfest.
