#!/usr/bin/env bash
# Multi-corner static timing: OpenSTA on the gate netlist with each corner's liberty, the SPEF that
# pex.sh extracted for that corner's RC corner, and the build's SDC (clocks propagated).
# usage: sta.sh <inputs_dir> <outdir> <pdk> [top]
#   inputs_dir holds <top>.vg, <top>.sdc and <top>.def.gz; pdk: skywater130 | ihp130 | gf180
#   env SPEF_DIR: where pex.sh wrote <top>.<rc>.spef (default <outdir>/pex; pex.sh is run there
#       first when a SPEF is missing)
#   env STA_RC=all: time every liberty corner with every RC corner (SKY130: 3 x 3 = 9 runs)
#       instead of each liberty corner with its own RC corner (slow+max, typical+nom, fast+min)
#   env STA_FAIL_ON_DRV=1: max slew / max capacitance violations fail the check as well (max fanout
#       is only reported)
# writes <outdir>/sta_<corner>.{log,setup.rpt,hold.rpt,setup.json,hold.json,drv.rpt,...}, sta.json;
# prints sta.json (one line).
# exit 0 = setup and hold met in every corner, 1 = a corner fails, 2 = a tool failed
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/common.sh"
signoff_init "$@" || exit 2
netlist=$IN/$TOP.vg; sdc=$IN/$TOP.sdc
for f in "$netlist" "$sdc"; do [ -f "$f" ] || { echo "missing input: $f" >&2; exit 2; }; done
start=$(date +%s.%N)
spef_dir=$(realpath -m "${SPEF_DIR:-$OUT/pex}")
for rc in $RC_CORNERS; do
  if [ ! -s "$spef_dir/$TOP.$rc.spef" ]; then
    bash "$here/pex.sh" "$IN" "$spef_dir" "$PDK_ID" "$TOP" > "$OUT/pex_run.out" 2>&1
    [ $? -eq 2 ] && { echo "pex.sh failed, see $OUT/pex_run.out" >&2; exit 2; }
    break
  fi
done
specs=()
for c in $CORNERS; do
  if [ "${STA_RC:-}" = "all" ]; then rcs=$RC_CORNERS; else rcs=$(pdk_get RC "$c"); fi
  for rc in $rcs; do
    name=$c; [ "${STA_RC:-}" = "all" ] && [ "$(echo $RC_CORNERS | wc -w)" -gt 1 ] && name=${c}_$rc
    spef=$spef_dir/$TOP.$rc.spef
    LIB=$(pdk_get LIB "$c") NETLIST=$netlist TOP=$TOP SDC=$sdc SPEF=$spef CORNER=$name OUT=$OUT \
      sta -no_init -exit "$here/sta.tcl" > "$OUT/sta_$name.log" 2>&1
    echo "sta exit=$?" >> "$OUT/sta_$name.log"
    specs+=("$name=$c:$rc:$spef")
  done
done
t=$(elapsed "$start")
ELAPSED_S=$t python3 -I "$here/sta_result.py" "$OUT" "$PDK_ID" "${specs[@]}" > "$OUT/sta.json"
res=$?
cat "$OUT/sta.json"
exit $res
