#!/usr/bin/env bash
# sky130A signoff on an SC result: KLayout DRC + Magic DRC + Magic/netgen LVS -> signoff.json
# usage: signoff_sky130.sh <layout.gds[.gz]> <netlist.v> <topcell> <outdir> [threads]
# The GDS may be SC's raw output (std cells are merged in from the PDK) or a full GDS.
# exit 0 = all clean, 1 = violations / mismatch, 2 = a tool failed
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
gds=$(realpath -m "$1"); netlist=$(realpath -m "$2"); top=$3; out=$(realpath -m "$4"); thr=${5:-4}
mkdir -p "$out"
bash "$here/drc_klayout.sh" "$gds" "$top" "$out/drc_klayout" "$thr" > "$out/drc_klayout.out" 2>&1; kl=$?
bash "$here/drc_magic.sh" "$gds" "$top" "$out/drc_magic" > "$out/drc_magic.out" 2>&1; mg=$?
bash "$here/lvs.sh" "$gds" "$netlist" "$top" "$out/lvs" > "$out/lvs.out" 2>&1; lv=$?
python3 - "$out" "$kl" "$mg" "$lv" <<'PY'
import json, os, sys
out, kl, mg, lv = sys.argv[1], *map(int, sys.argv[2:])
def load(p):
    p = os.path.join(out, p)
    return json.load(open(p)) if os.path.exists(p) else None
res = {"klayout_drc": {"exit": kl, **(load("drc_klayout/drc.json") or {})},
       "magic_drc": {"exit": mg, **(load("drc_magic/magic_drc.json") or {})},
       "lvs": {"exit": lv, **(load("lvs/lvs_result.json") or {})}}
res["clean"] = kl == 0 and mg == 0 and lv == 0
json.dump(res, open(os.path.join(out, "signoff.json"), "w"), indent=1)
print(json.dumps(res))
PY
[ $kl -eq 2 ] || [ $mg -eq 2 ] || [ $lv -eq 2 ] && exit 2
[ $kl -eq 0 ] && [ $mg -eq 0 ] && [ $lv -eq 0 ] && exit 0
exit 1
