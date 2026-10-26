#!/usr/bin/env bash
# Density check for IHP SG13G2 with IHP's KLayout density deck (run_drc.py --density_only, which
# runs rule_decks/density.drc): global min/max density of Activ, GatPoly, Metal1-5, TopMetal1-2
# (AFil.g/g1, GFil.g, M1.j/k ... M5.j/k, TM1.c/d, TM2.c/d, LBE.i) and the 800x800 um window rules
# (AFil.g2/g3, M1Fil.h/k ... M5Fil.h/k).
# usage: density_ihp.sh <layout.gds[.gz]> <topcell> <outdir> [threads]
# These are chip-level rules: a block without fill fails them (the IHP fill scripts only fill
# inside a seal ring, i.e. on the finished chip). Treat the result as information for a block.
# writes <outdir>/density.lyrdb, density.log, density.json (per-layer area/density/limits + the
# violated rules); exit 0 = every density rule holds, 1 = some do not, 2 = tool failure
set -uo pipefail
gds=$(realpath -m "$1"); top=$2; out=$(realpath -m "$3"); thr=${4:-4}
here=$(cd "$(dirname "$0")" && pwd)
runner=${PDK_ROOT:-/foss/pdks}/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py
mkdir -p "$out"
rm -rf "$out/run"
start=$(date +%s.%N)
python3 "$runner" --path="$gds" --topcell="$top" --run_dir="$out/run" --mp=1 \
  --density_thr="$thr" --density_only > "$out/density.log" 2>&1
echo "run_drc.py exit=$? time=$(echo "$(date +%s.%N) - $start" | bc)s" | tee -a "$out/density.log"
grep -q -e "KLayout DRC Check Passed" -e "Violations were detected" "$out/density.log" || exit 2
db=$(ls "$out"/run/*_density.lyrdb 2>/dev/null | head -1)
log=$(ls "$out"/run/*_density.log 2>/dev/null | head -1)
[ -n "$db" ] && [ -n "$log" ] || exit 2
cp "$db" "$out/density.lyrdb"
python3 - "$log" "$out/density.lyrdb" "$here/lyrdb_count.py" "$out/density.json" <<'PY'
import json, re, subprocess, sys
log, db, counter, dst = sys.argv[1:5]
layers, total = {}, None
for line in open(log, errors="replace"):
    line = line.split(" : ", 1)[-1].strip()
    m = re.match(r"Total Area\s*=\s*([\d.]+)", line)
    if m:
        total = float(m.group(1))
    m = re.match(r"(\w+)\s+Area\s*=\s*([\d.]+)", line)
    if m and m.group(1) != "Total":
        layers.setdefault(m.group(1), {})["area_um2"] = float(m.group(2))
    m = re.match(r"(\w+)\s+Density %\s*=\s*([\d.]+)%\s*\[(.*)\]", line)
    if m:
        d = layers.setdefault(m.group(1), {})
        d["density_pct"] = float(m.group(2))
        for k, v in re.findall(r"(Min|Max)\s*=\s*([\d.]+)%", m.group(3)):
            d[k.lower() + "_pct"] = float(v)
counts = json.loads(subprocess.run([sys.executable, counter, db], capture_output=True,
                                   text=True, check=True).stdout)
res = {"total": counts["total"], "violated": counts["violated"],
       "rules_checked": counts["rules_checked"], "area_um2": total, "layers": layers}
json.dump(res, open(dst, "w"))
print(json.dumps(res))
PY
[ $? -eq 0 ] || exit 2
total=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["total"])' "$out/density.json")
[ "$total" = "0" ] && exit 0 || exit 1
