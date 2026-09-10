#!/usr/bin/env bash
# Convert a PowerPoint report (e.g. the monthly MSR deck) to a
# print-ready PDF with LibreOffice.
#
# Office decks written since 2023 default to the Aptos font family,
# which LibreOffice does not ship. Without intervention it substitutes
# the much wider DejaVu Sans, which can push dense tables past the
# bottom of the slide (text overlapping footnotes/footers in the PDF).
# This script installs a user-level fontconfig alias mapping the Aptos
# family to Carlito (metric-compatible with Calibri, Aptos's
# predecessor), which keeps text widths close to the original so
# layouts survive the conversion.
#
# Usage: scripts/pptx_to_pdf.sh report.pptx [outdir]
#   Writes report.pdf next to the input (or into outdir).
#
# Requires: libreoffice-impress, fontconfig, fonts-crosextra-carlito
#   (Debian/Ubuntu: apt-get install libreoffice-impress fonts-crosextra-carlito)
#
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ewan Douglas and contributors
set -euo pipefail

if [ $# -lt 1 ] || [ ! -f "$1" ]; then
  echo "usage: $0 <deck.pptx> [outdir]" >&2
  exit 2
fi
src=$(readlink -f "$1")
outdir=$(readlink -f "${2:-$(dirname "$src")}")

if ! command -v soffice > /dev/null; then
  echo "error: LibreOffice (soffice) not found — install libreoffice-impress" >&2
  exit 1
fi

# Map Aptos -> Carlito at the user level unless the system already
# resolves Aptos to a real or metric-compatible font.
match=$(fc-match Aptos 2> /dev/null || true)
case "$match" in
  *Aptos* | *Carlito*) ;;
  *)
    conf_dir="${XDG_CONFIG_HOME:-$HOME/.config}/fontconfig/conf.d"
    mkdir -p "$conf_dir"
    cat > "$conf_dir/60-aptos-carlito.conf" << 'EOF'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <alias binding="same"><family>Aptos</family><prefer><family>Carlito</family></prefer></alias>
  <alias binding="same"><family>Aptos Narrow</family><prefer><family>Carlito</family></prefer></alias>
  <alias binding="same"><family>Aptos Display</family><prefer><family>Carlito</family></prefer></alias>
</fontconfig>
EOF
    fc-cache -f > /dev/null 2>&1 || true
    echo "note: aliased Aptos -> Carlito in $conf_dir/60-aptos-carlito.conf"
    ;;
esac

# A throwaway profile avoids clashing with (or hanging on) a running
# LibreOffice instance, e.g. in CI containers.
profile=$(mktemp -d)
trap 'rm -rf "$profile"' EXIT
soffice --headless "-env:UserInstallation=file://$profile" \
  --convert-to pdf --outdir "$outdir" "$src"

pdf="$outdir/$(basename "${src%.*}").pdf"
[ -f "$pdf" ] || { echo "error: conversion produced no PDF" >&2; exit 1; }
echo "wrote $pdf"
