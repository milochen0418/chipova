#!/usr/bin/env bash
# Density check for GF180MCU: the open_pdks deck's density rules (gf180mcu.drc -rd decks=density,
# what LibreLane runs as its separate density check) plus the per-layer numbers, which that deck
# does not print (layer_density.py: merged area / layout extent, drawn + dummy datatypes).
# usage: density_gf180.sh <layout.gds[.gz]> <topcell> <outdir> [threads]
# Chip-level rules (e.g. M2.4 "Metal2 coverage over the entire die shall be >30%"): a block
# without dummy fill fails them; treat the result as information for a block.
# writes <outdir>/drc.lyrdb, drc.log, drc.json, layers.json, density.json; exit 0 = holds, 1 = violations, 2 = failure
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
gds=$(realpath -m "$1"); top=$2; out=$(realpath -m "$3"); thr=${4:-4}
mkdir -p "$out"
bash "$here/drc_gf180_klayout.sh" "$gds" "$top" "$out" "$thr" density > "$out/drc_run.out" 2>&1
rc=$?
[ $rc -eq 2 ] && { cat "$out/drc_run.out"; exit 2; }
python3 "$here/layer_density.py" "$gds" "$top" --pdk gf180 > "$out/layers.json" || exit 2
python3 - "$out/drc.json" "$out/layers.json" "$out/density.json" <<'PY'
import json, sys
drc, layers, dst = (json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), sys.argv[3])
res = {"total": drc["total"], "violated": drc["violated"], **layers}
json.dump(res, open(dst, "w")); print(json.dumps(res))
PY
exit $rc
