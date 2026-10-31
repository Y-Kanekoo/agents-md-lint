#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="$PWD/.cache/uv"
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src
uv run pytest
