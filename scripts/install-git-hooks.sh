#!/usr/bin/env sh

set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

git -C "$repo_root" config --local core.hooksPath .githooks
printf '%s\n' "Installed git hooks from .githooks"
