#!/usr/bin/env bash
# LVS for sky130A (sky130_fd_sc_hd): Magic extraction from GDS + netgen against the Verilog netlist.
# usage: lvs.sh <layout.gds[.gz]> <netlist.v> <topcell> <outdir>
# The GDS must contain real std-cell layouts; SC 0.38/lambdapdk output has LEF abstracts, so this
# script first merges the real cells from the PDK (gds_merge_cells.py). Fill/tap cells are ignored
# by the PDK netgen setup when MAGIC_EXT_USE_GDS=1. The netlist gets VPB/VNB tied to VPWR/VGND
# (add_bulk_pins.py), since SC's netlist leaves the body pins out.
# exit 0 = "Circuits match uniquely", 1 = mismatch, 2 = tool failure
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
gds=$(realpath -m "$1"); netlist=$(realpath -m "$2"); top=$3; out=$(realpath -m "$4")
pdk=${PDK_ROOT:-/foss/pdks}/sky130A
export CELL_SPICE=$pdk/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice
mkdir -p "$out"
t0=$(date +%s.%N)
python3 "$here/gds_merge_cells.py" "$gds" "$out/$top.full.gds" "$top" \
  "$pdk/libs.ref/sky130_fd_sc_hd/gds/sky130_fd_sc_hd.gds" > "$out/merge.log" 2>&1 || exit 2
export GDS=$out/$top.full.gds TOP=$top OUT=$out
(cd "$out" && magic -dnull -noconsole -rcfile "$pdk/libs.tech/magic/sky130A.magicrc" \
   "$here/magic_extract.tcl" < /dev/null > extract.log 2>&1) || exit 2
[ -s "$out/$top.spice" ] || { echo "no extracted netlist"; exit 2; }
t1=$(date +%s.%N)
python3 "$here/add_bulk_pins.py" "$netlist" "$out/$top.pwr.v" > "$out/netlist_fix.log" 2>&1 || exit 2
export LAYOUT_SPICE=$out/$top.spice NETLIST_V=$out/$top.pwr.v SETUP=$pdk/libs.tech/netgen/sky130A_setup.tcl \
       REPORT=$out/lvs.rpt MAGIC_EXT_USE_GDS=1
(cd "$out" && netgen -batch source "$here/netgen_lvs.tcl" < /dev/null > netgen.log 2>&1)
t2=$(date +%s.%N)
echo "extract=$(echo "$t1 - $t0" | bc)s netgen=$(echo "$t2 - $t1" | bc)s"
python3 "$here/lvs_result.py" "$out/lvs.rpt" "$out/lvs.json" | tee "$out/lvs_result.json"
rc=${PIPESTATUS[0]}
[ -s "$out/lvs.rpt" ] || exit 2
exit $rc
