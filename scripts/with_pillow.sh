#!/usr/bin/env bash
# Run a command inside a nix env that has Python + Pillow.
# This host uses a pinned flake and has no project virtualenv; the fetch stage
# is deliberately stdlib-only, so only the image stages need this wrapper.
exec nix shell --impure --expr \
  'with builtins.getFlake "nixpkgs"; legacyPackages.${builtins.currentSystem}.python3.withPackages (ps: [ ps.pillow ])' \
  --command "$@"
