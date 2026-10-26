#!/usr/bin/env bash
# KLayout DRC for GF180MCU with the open_pdks deck in the image (gf180mcuD/libs.tech/klayout/tech/
# drc/gf180mcu.drc), the rule set LibreLane signs off with: decks "all,-antenna,-density".
# usage: drc_gf180_klayout.sh <layout.gds|.gds.gz> <topcell> <outdir> [threads] [decks]
#   decks: the deck's tag list (default all,-antenna,-density; e.g. "density", "antenna", "all")
# env VARIANT: metal stack preset of the deck (default gf180mcuC = 5 metals, 9 kA top metal, MIM B:
#   what SiliconCompiler's gf180_demo target builds, lambdapdk GF180_5LM_1TM_9K). gf180mcuD = 5
#   metals with 11 kA top metal (the image's open_pdks variant).
# The GDS must hold the real std-cell layouts (SC's GF180 output does; check with gds_cell_check.py).
# writes <outdir>/drc.lyrdb, drc.log, drc.json; exit 0 = clean, 1 = violations, 2 = tool failure
set -uo pipefail
gds=$(realpath -m "$1"); top=$2; out=$(realpath -m "$3"); thr=${4:-4}; decks=${5:-all,-antenna,-density}
here=$(cd "$(dirname "$0")" && pwd)
deck=${PDK_ROOT:-/foss/pdks}/gf180mcuD/libs.tech/klayout/tech/drc/gf180mcu.drc
variant=${VARIANT:-gf180mcuC}
mkdir -p "$out"
rm -f "$out/drc.lyrdb"
start=$(date +%s.%N)
klayout -b -r "$deck" -rd input="$gds" -rd topcell="$top" -rd report="$out/drc.lyrdb" \
  -rd variant="$variant" -rd decks="$decks" -rd threads="$thr" -rd run_mode=deep > "$out/drc.log" 2>&1
rc=$?
echo "klayout exit=$rc time=$(echo "$(date +%s.%N) - $start" | bc)s" | tee -a "$out/drc.log"
[ $rc -eq 0 ] && [ -f "$out/drc.lyrdb" ] || exit 2
python3 "$here/lyrdb_count.py" "$out/drc.lyrdb" > "$out/drc.json" || exit 2
python3 - "$out/drc.json" "$variant" "$decks" <<'PY'
import json, sys
p, v, d = sys.argv[1:4]
r = json.load(open(p)); r["variant"] = v; r["decks"] = d
json.dump(r, open(p, "w")); print(json.dumps(r))
PY
total=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["total"])' "$out/drc.json")
[ "$total" = "0" ] && exit 0 || exit 1
