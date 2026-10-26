#!/usr/bin/env bash
# Antenna rule check: OpenROAD check_antennas on a Build ASIC run's routed DEF, with the PDK's tech
# LEF (ANTENNA* ratios per layer) and cell LEF (ANTENNAGATEAREA/ANTENNADIFFAREA per pin).
# usage: antenna.sh <inputs_dir> <outdir> <pdk> [top]
#   inputs_dir holds <top>.def.gz; pdk: skywater130 | ihp130 | gf180
# writes <outdir>/antenna.rpt (violating nets: pin, layer, ratio, required ratio), antenna.log,
# antenna.json, pdk_files.json; prints antenna.json (one line).
# exit 0 = no violation, 1 = violations found, 2 = the tool failed / nothing to check
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/common.sh"
signoff_init "$@" || exit 2
start=$(date +%s.%N)
rm -f "$OUT/antenna.rpt"
TECH_LEF=$TECH_LEF CELL_LEF=$CELL_LEF DEF=$DEF OUT=$OUT \
  openroad -no_init -exit "$here/antenna.tcl" > "$OUT/antenna.log" 2>&1
rc=$?
t=$(elapsed "$start")
echo "openroad exit=$rc time=${t}s" >> "$OUT/antenna.log"
ELAPSED_S=$t PDK_FILES=$OUT/pdk_files.json \
  python3 -I "$here/antenna_result.py" "$OUT/antenna.rpt" "$OUT/antenna.log" "$CELL_LEF" "$DEF" "$PDK_ID" \
  > "$OUT/antenna.json"
res=$?
cat "$OUT/antenna.json"
[ $rc -eq 0 ] || exit 2
exit $res
