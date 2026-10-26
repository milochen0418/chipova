#!/usr/bin/env bash
# LVS for GF180MCU (gf180mcu_fd_sc_mcu9t5v0) with the open_pdks KLayout deck in the image
# (gf180mcuD/libs.tech/klayout/tech/lvs/run_lvs.py + gf180mcu.lvs), against the gate-level Verilog.
# usage: lvs_gf180_klayout.sh <layout.gds[.gz]> <netlist.v> <topcell> <outdir>
# env VARIANT: run_lvs.py --variant (default C = 5 metals, 9 kA top metal: SC's gf180_demo stack;
#   D = 11 kA top metal). The metal option does not change std-cell extraction.
# 1. vg2spice.py: Verilog -> CDL with the cells' .SUBCKTs from the PDK CDL; SC's netlist connects
#    only VDD/VSS, the cells also have the body pins VNW/VPW: tied to the instance's VDD/VSS nets.
# 2. run_lvs.py --run_mode=deep (hierarchical: each cell once, then the top), ports checked.
# 3. lvsdb_summary.py -> lvs_result.json ("net_warnings" lists supply nets KLayout flags while the
#    circuits match, see REPORT.md).
# exit 0 = "Congratulations! Netlists match.", 1 = no match, 2 = tool failure
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
gds=$(realpath -m "$1"); netlist=$(realpath -m "$2"); top=$3; out=$(realpath -m "$4")
pdk=${PDK_ROOT:-/foss/pdks}/gf180mcuD
lib=${STDCELL_LIB:-gf180mcu_fd_sc_mcu9t5v0}
cdl=$pdk/libs.ref/$lib/cdl/$lib.cdl
mkdir -p "$out"
rm -rf "$out/run"
t0=$(date +%s.%N)
python3 "$here/vg2spice.py" "$netlist" "$cdl" -o "$out/$top.cdl" --top "$top" \
  --tie VNW=@VDD --tie VPW=@VSS > "$out/vg2spice.json" || { cat "$out/vg2spice.json"; exit 2; }
python3 "$pdk/libs.tech/klayout/tech/lvs/run_lvs.py" --layout="$gds" --netlist="$out/$top.cdl" \
  --variant="${VARIANT:-C}" --topcell="$top" --run_dir="$out/run" --run_mode=deep --thr=2 \
  > "$out/lvs.log" 2>&1
rc=$?
echo "run_lvs.py exit=$rc time=$(echo "$(date +%s.%N) - $t0" | bc)s" | tee -a "$out/lvs.log"
base=$(basename "$gds"); base=${base%%.*}
# the deck logs its verdict to stdout only (lvs.log)
python3 "$here/lvsdb_summary.py" "$out/run/$base.lvsdb" "$out/lvs.log" > "$out/lvs_result.json"
res=$?
cat "$out/lvs_result.json"
exit $res
