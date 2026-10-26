#!/usr/bin/env bash
# Parasitic extraction: OpenRCX (OpenROAD extract_parasitics) on a Build ASIC run's routed DEF with
# the PDK's own OpenRCX rules, one SPEF per RC corner (each corner in its own OpenROAD process, with
# that corner's tech LEF, since OpenRCX takes via resistances from the tech LEF).
# usage: pex.sh <inputs_dir> <outdir> <pdk> [top]
#   inputs_dir holds <top>.def.gz (and optionally <top>.typical.spef, the build's own SPEF, which is
#   summarised next to ours for comparison); pdk: skywater130 | ihp130 | gf180
# writes <outdir>/<top>.<rc>.spef, pex_<rc>.log, pex.json, pdk_files.json; prints pex.json.
# exit 0 = every RC corner extracted and every routed signal net is in its SPEF,
#      1 = nets missing from a SPEF or signal nets without routing, 2 = a tool failed
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/common.sh"
signoff_init "$@" || exit 2
start=$(date +%s.%N)
rc_all=0
for rc in $RC_CORNERS; do
  rm -f "$OUT/$TOP.$rc.spef"
  TLEF=$(pdk_get TLEF "$rc") CELL_LEF=$CELL_LEF DEF=$DEF RULES=$(pdk_get RCX "$rc") RC=$rc \
  SPEF=$OUT/$TOP.$rc.spef \
    openroad -no_init -exit "$here/pex.tcl" > "$OUT/pex_$rc.log" 2>&1
  r=$?
  echo "openroad exit=$r" >> "$OUT/pex_$rc.log"
  [ $r -eq 0 ] || rc_all=2
done
t=$(elapsed "$start")
BUILD_SPEF=$IN/$TOP.typical.spef ELAPSED_S=$t \
  python3 -I "$here/pex_result.py" "$OUT" "$TOP" "$PDK_ID" $RC_CORNERS > "$OUT/pex.json"
res=$?
cat "$OUT/pex.json"
[ $rc_all -eq 0 ] || exit 2
exit $res
