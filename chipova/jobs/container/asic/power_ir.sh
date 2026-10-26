#!/usr/bin/env bash
# Power and static IR drop per corner: OpenROAD reads the routed DEF, the corner's liberty and the
# corner's extracted SPEF (pex.sh), reports power (OpenSTA report_power) and runs PDNSim
# (analyze_power_grid) on every power and ground net of the DEF, with the net's voltage set to the
# corner's supply (ground 0 V). One OpenROAD process per corner.
# usage: power_ir.sh <inputs_dir> <outdir> <pdk> [top]
#   inputs_dir holds <top>.def.gz and <top>.sdc; pdk: skywater130 | ihp130 | gf180
#   env SPEF_DIR: where pex.sh wrote <top>.<rc>.spef (default <outdir>/pex; run first if missing)
#   env ACTIVITY (default 0.2): vectorless toggle rate, transitions per clock cycle, with duty 0.5;
#       ACTIVITY_MODE=global (default): every non-clock pin (set_power_activity -global ...);
#       ACTIVITY_MODE=input: primary inputs only, propagated by OpenSTA (set_power_activity -input
#       ...), which leaves register loops such as counters at 0 activity
#   env VCD + VCD_SCOPE: use a simulation's activity instead (read_vcd -scope $VCD_SCOPE $VCD)
#   env IR_RC: tech LEF (PDN resistance) for every corner's IR, e.g. max for the worst case;
#       default: each corner's own RC corner (SKY130 slow=max, typical=nom, fast=min)
#   env IR_LIMIT_PCT (default 5), POWER_LIMIT_MW (optional): see power_result.py
# writes <outdir>/power_<c>.{log,rpt,json,activity.rpt}, ir_<c>_<net>.{csv,errors}, em_<c>_<net>.csv,
# power_ir.json; prints power_ir.json (one line).
# exit 0 = IR within the limit and every supply net connected, 1 = not, 2 = a tool failed
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/common.sh"
signoff_init "$@" || exit 2
sdc=$IN/$TOP.sdc
[ -f "$sdc" ] || { echo "missing input: $sdc" >&2; exit 2; }
if [ -n "${VCD:-}" ] && [ ! -f "$VCD" ]; then echo "missing VCD: $VCD" >&2; exit 2; fi
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
  rc=$(pdk_get RC "$c")
  irc=${IR_RC:-$rc}
  tlef=$(pdk_get TLEF "$irc"); [ -n "$tlef" ] || tlef=$TECH_LEF
  spef=$spef_dir/$TOP.$rc.spef
  TLEF=$tlef CELL_LEF=$CELL_LEF DEF=$DEF LIB=$(pdk_get LIB "$c") SDC=$sdc SPEF=$spef CORNER=$c \
  VDD=$(pdk_get VDD "$c") ACTIVITY=${ACTIVITY:-0.2} ACTIVITY_MODE=${ACTIVITY_MODE:-global} OUT=$OUT VCD=${VCD:-} VCD_SCOPE=${VCD_SCOPE:-} \
  CUT_LAYERS=${CUT_LAYERS:-} CUT_RES=$(pdk_get CUTRES "$irc") \
    openroad -no_init -exit "$here/power_ir.tcl" > "$OUT/power_$c.log" 2>&1
  echo "openroad exit=$?" >> "$OUT/power_$c.log"
  specs+=("$c=$rc:$spef:$tlef")
done
t=$(elapsed "$start")
ELAPSED_S=$t python3 -I "$here/power_result.py" "$OUT" "$PDK_ID" "${specs[@]}" > "$OUT/power_ir.json"
res=$?
cat "$OUT/power_ir.json"
exit $res
