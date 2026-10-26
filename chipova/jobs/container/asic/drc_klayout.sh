#!/usr/bin/env bash
# KLayout DRC for sky130A with the open_pdks deck shipped in the image.
# usage: drc_klayout.sh <layout.gds|.gds.gz> <topcell> <outdir> [threads]
# env STDCELL_GDS: library GDS merged in first (default: sky130_fd_sc_hd from the PDK, needed for
#   SC 0.38 output whose std cells are LEF abstracts); STDCELL_GDS=none to check the file as is.
# writes <outdir>/drc.lyrdb (KLayout marker DB), drc.log, drc.json; exit 0 = clean,
# 1 = violations found, 2 = tool failure.
set -uo pipefail
gds=$(realpath -m "$1"); top=$2; out=$(realpath -m "$3"); thr=${4:-4}
here=$(cd "$(dirname "$0")" && pwd)
pdk=${PDK_ROOT:-/foss/pdks}/sky130A
deck=$pdk/libs.tech/klayout/drc/sky130A_mr.drc
lib=${STDCELL_GDS:-$pdk/libs.ref/sky130_fd_sc_hd/gds/sky130_fd_sc_hd.gds}
mkdir -p "$out"
if [ "$lib" != "none" ]; then
  python3 "$here/gds_merge_cells.py" "$gds" "$out/$top.full.gds" "$top" "$lib" > "$out/merge.log" 2>&1 || exit 2
  gds=$out/$top.full.gds
fi
start=$(date +%s.%N)
# Rule groups are all OFF by default in this deck -> switch on feol/beol/offgrid explicitly.
klayout -b -r "$deck" \
  -rd input="$gds" -rd top_cell="$top" -rd report="$out/drc.lyrdb" \
  -rd feol=true -rd beol=true -rd offgrid=true -rd floating_met=false -rd seal=false \
  -rd thr="$thr" > "$out/drc.log" 2>&1
rc=$?
echo "klayout exit=$rc time=$(echo "$(date +%s.%N) - $start" | bc)s" | tee -a "$out/drc.log"
[ $rc -eq 0 ] && [ -f "$out/drc.lyrdb" ] || exit 2
python3 "$here/lyrdb_count.py" "$out/drc.lyrdb" | tee "$out/drc.json"
total=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["total"])' "$out/drc.json")
[ "$total" = "0" ] && exit 0 || exit 1
