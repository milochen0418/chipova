#!/usr/bin/env bash
# LVS for IHP SG13G2 with IHP's own KLayout deck (the PDK's run_lvs.py + sg13g2.lvs), against the
# gate-level Verilog netlist of a Build ASIC run.
# usage: lvs_ihp_klayout.sh <layout.gds[.gz]> <netlist.v> <topcell> <outdir>
# 1. vg2spice.py turns the Verilog into a CDL netlist (<outdir>/<top>.cdl) with the std cells'
#    transistor-level .SUBCKTs from the PDK's sg13g2_stdcell.cdl copied in.
# 2. run_lvs.py extracts the layout hierarchically (--run_mode deep: each std cell is extracted
#    and compared once, then the top level) and compares it in strict port mode (the top-level
#    pins clk/.../VDD/VSS must be labelled in the layout).
#    Flat mode does NOT work on std-cell blocks: the cells' pin labels become top-level pins.
# 3. lvsdb_summary.py reads the verdict and the cross-reference -> lvs_result.json.
# writes <outdir>/<top>.cdl, run/ (KLayout .lvsdb, extracted .cir, logs), lvs.log, lvs_result.json
# exit 0 = "Congratulations! Netlists match.", 1 = no match, 2 = tool failure
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
gds=$(realpath -m "$1"); netlist=$(realpath -m "$2"); top=$3; out=$(realpath -m "$4")
pdk=${PDK_ROOT:-/foss/pdks}/ihp-sg13g2
cdl=$pdk/libs.ref/sg13g2_stdcell/cdl/sg13g2_stdcell.cdl
mkdir -p "$out"
rm -rf "$out/run"
t0=$(date +%s.%N)
python3 "$here/vg2spice.py" "$netlist" "$cdl" -o "$out/$top.cdl" --top "$top" > "$out/vg2spice.json" || {
  cat "$out/vg2spice.json"; exit 2; }
python3 "$pdk/libs.tech/klayout/tech/lvs/run_lvs.py" --layout="$gds" --netlist="$out/$top.cdl" \
  --topcell="$top" --run_dir="$out/run" --run_mode=deep > "$out/lvs.log" 2>&1
rc=$?
t1=$(date +%s.%N)
echo "run_lvs.py exit=$rc time=$(echo "$t1 - $t0" | bc)s" | tee -a "$out/lvs.log"
# KLayout names its db and log after the layout file: <name up to the first dot>.lvsdb / .log
base=$(basename "$gds"); base=${base%%.*}
python3 "$here/lvsdb_summary.py" "$out/run/$base.lvsdb" "$out/run/$base.log" > "$out/lvs_result.json"
res=$?
cat "$out/lvs_result.json"
exit $res
