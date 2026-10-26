#!/usr/bin/env bash
# LVS for GF180MCU with Magic extraction + Netgen (the image's gf180mcuD.magicrc and
# gf180mcuD_setup.tcl; LibreLane's GF180 LVS), against the gate-level Verilog.
# usage: lvs_gf180_magic.sh <layout.gds[.gz]> <netlist.v> <topcell> <outdir>
# The Verilog becomes a SPICE netlist first (vg2spice.py, cells from the PDK's std-cell .spice,
# body pins VNW/VPW tied to the instance's VDD/VSS nets), so no Verilog body-pin patch is needed.
# exit 0 = "Circuits match uniquely", 1 = mismatch, 2 = tool failure
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
gds=$(realpath -m "$1"); netlist=$(realpath -m "$2"); top=$3; out=$(realpath -m "$4")
pdk=${PDK_ROOT:-/foss/pdks}/gf180mcuD
lib=${STDCELL_LIB:-gf180mcu_fd_sc_mcu9t5v0}
export CELL_SPICE=$pdk/libs.ref/$lib/spice/$lib.spice
mkdir -p "$out"
t0=$(date +%s.%N)
python3 "$here/vg2spice.py" "$netlist" "$CELL_SPICE" -o "$out/$top.schematic.spice" --top "$top" \
  --tie VNW=@VDD --tie VPW=@VSS > "$out/vg2spice.json" || { cat "$out/vg2spice.json"; exit 2; }
export GDS=$gds TOP=$top OUT=$out
(cd "$out" && magic -dnull -noconsole -rcfile "$pdk/libs.tech/magic/gf180mcuD.magicrc" \
   "$here/magic_extract.tcl" < /dev/null > extract.log 2>&1) || exit 2
[ -s "$out/$top.spice" ] || { echo "no extracted netlist"; exit 2; }
t1=$(date +%s.%N)
export LAYOUT_SPICE=$out/$top.spice NETLIST_SPICE=$out/$top.schematic.spice \
       SETUP=$pdk/libs.tech/netgen/gf180mcuD_setup.tcl REPORT=$out/lvs.rpt
(cd "$out" && netgen -batch source "$here/netgen_lvs_spice.tcl" < /dev/null > netgen.log 2>&1)
t2=$(date +%s.%N)
echo "extract=$(echo "$t1 - $t0" | bc)s netgen=$(echo "$t2 - $t1" | bc)s"
[ -s "$out/lvs.rpt" ] || exit 2
python3 "$here/lvs_result.py" "$out/lvs.rpt" "$out/lvs.json" | tee "$out/lvs_result.json"
exit ${PIPESTATUS[0]}
