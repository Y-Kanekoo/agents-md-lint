#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="$PWD/.cache/uv"
printf '%s\n' '=== 問題を含む例 ==='
status=0
uv run agents-md-lint examples/bad-repo || status=$?
if [ "$status" -ne 1 ]; then
    printf '%s\n' '問題を含む例の終了コードが想定と異なります' >&2
    exit 1
fi
printf '%s\n' '=== 問題のない例 ==='
uv run agents-md-lint examples/good-repo
