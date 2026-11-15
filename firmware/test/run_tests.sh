#!/bin/sh
# 主機端單元測試：韌體純邏輯（src/core/*.h）
# 用法：sh firmware/test/run_tests.sh   （macOS 內建 clang 或 Linux g++/clang 皆可）
set -eu
cd "$(dirname "$0")"
CXX="${CXX:-c++}"
OUT="${TMPDIR:-/tmp}/mod_ask_test_core.$$"
trap 'rm -f "$OUT"' EXIT
FLAGS="-std=c++17 -O1 -g -Wall -Wextra -Wpedantic -Werror -Wshadow -Wconversion -Wno-sign-conversion"
SAN="-fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all"
echo "compiler: $($CXX --version | head -1)"
echo "flags: $FLAGS $SAN"
$CXX $FLAGS $SAN test_core.cpp -o "$OUT"
"$OUT"
