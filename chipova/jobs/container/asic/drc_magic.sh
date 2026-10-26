#!/usr/bin/env bash
# Magic DRC for sky130A. usage: drc_magic.sh <layout.gds|.gds.gz> <topcell> <outdir>
# env STDCELL_GDS as in drc_klayout.sh (std cells merged in first unless STDCELL_GDS=none).
# writes <outdir>/magic_drc.rpt, magic_drc.log, magic_drc.json; exit 0 = clean, 1 = violations,
# 2 = failure
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
gds=$(realpath -m "$1"); top=$2; out=$(realpath -m "$3")
pdk=${PDK_ROOT:-/foss/pdks}/sky130A
lib=${STDCELL_GDS:-$pdk/libs.ref/sky130_fd_sc_hd/gds/sky130_fd_sc_hd.gds}
mkdir -p "$out"
if [ "$lib" != "none" ]; then
  python3 "$here/gds_merge_cells.py" "$gds" "$out/$top.full.gds" "$top" "$lib" > "$out/merge.log" 2>&1 || exit 2
  gds=$out/$top.full.gds
fi
export GDS=$gds TOP=$top OUT=$out
start=$(date +%s.%N)
(cd "$out" && magic -dnull -noconsole -rcfile "$pdk/libs.tech/magic/sky130A.magicrc" \
  "$here/magic_drc.tcl" < /dev/null > magic_drc.log 2>&1)
rc=$?
echo "magic exit=$rc time=$(echo "$(date +%s.%N) - $start" | bc)s" | tee -a "$out/magic_drc.log"
n=$(sed -n 's/^MAGIC_DRC_COUNT: //p' "$out/magic_drc.log" | tail -1)
[ -n "$n" ] || exit 2
echo "{\"total\": $n}" | tee "$out/magic_drc.json"
[ "$n" = "0" ] && exit 0 || exit 1
