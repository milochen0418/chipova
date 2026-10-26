#!/usr/bin/env bash
# LVS for IHP SG13G2 with Magic extraction + Netgen (the PDK's ihp-sg13g2.magicrc and
# ihp-sg13g2_setup.tcl), against the gate-level Verilog netlist. Same scripts as the SKY130 LVS
# (magic_extract.tcl, netgen_lvs.tcl); IHP cells have no separate body pins, so the netlist is
# used as is. Fill and decap cells are handled by the PDK's netgen setup.
# usage: lvs_ihp_magic.sh <layout.gds[.gz]> <netlist.v> <topcell> <outdir>
# exit 0 = "Circuits match uniquely", 1 = mismatch, 2 = tool failure
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
gds=$(realpath -m "$1"); netlist=$(realpath -m "$2"); top=$3; out=$(realpath -m "$4")
pdk=${PDK_ROOT:-/foss/pdks}/ihp-sg13g2
export CELL_SPICE=${CELL_SPICE:-$pdk/libs.ref/sg13g2_stdcell/spice/sg13g2_stdcell.spice}
mkdir -p "$out"
t0=$(date +%s.%N)
export GDS=$gds TOP=$top OUT=$out
(cd "$out" && magic -dnull -noconsole -rcfile "$pdk/libs.tech/magic/ihp-sg13g2.magicrc" \
   "$here/magic_extract.tcl" < /dev/null > extract.log 2>&1) || exit 2
[ -s "$out/$top.spice" ] || { echo "no extracted netlist"; exit 2; }
t1=$(date +%s.%N)
export LAYOUT_SPICE=$out/$top.spice NETLIST_V=$netlist SETUP=$pdk/libs.tech/netgen/ihp-sg13g2_setup.tcl \
       REPORT=$out/lvs.rpt
(cd "$out" && netgen -batch source "$here/netgen_lvs.tcl" < /dev/null > netgen.log 2>&1)
t2=$(date +%s.%N)
echo "extract=$(echo "$t1 - $t0" | bc)s netgen=$(echo "$t2 - $t1" | bc)s"
[ -s "$out/lvs.rpt" ] || exit 2
python3 "$here/lvs_result.py" "$out/lvs.rpt" "$out/lvs.json" | tee "$out/lvs_result.json"
exit ${PIPESTATUS[0]}
