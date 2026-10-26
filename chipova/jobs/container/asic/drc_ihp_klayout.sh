#!/usr/bin/env bash
# KLayout DRC for IHP SG13G2 with IHP's own decks (the PDK's run_drc.py + ihp-sg13g2.drc).
# usage: drc_ihp_klayout.sh <layout.gds|.gds.gz> <topcell> <outdir> [threads] [ruleset]
#   ruleset  minimum (default): run_drc.py --minimum_drc = the "SG13G2 minimum layout rule set
#                     required for foundry prechecks" (Rev. 1.2 + M5.j/M5.k/forbidden.NoDRC), the
#                     set IHP's tape-out precheck checks; no offgrid/angle/extra/antenna rules
#            main:    the main rule set (ihp-sg13g2.drc incl. offgrid, angle, pin, forbidden) without
#                     the recommended rules and without the unverified extra rules = what LibreLane
#                     signs off with (KLAYOUT_DRC_OPTIONS no_recommended=true, run_mode=deep)
#            full:    run_drc.py's default: main + recommended + extra ("maximal") rules
# Density rules are left out (--no_density): they are chip-level rules that only hold after fill;
# density_ihp.sh reports them. env DENSITY=1 keeps them in this run; env ANTENNA=1 adds the
# antenna deck (not with minimum). The GDS must hold the real std-cell layouts (SC's IHP output
# does; gds_cell_check.py checks it).
# writes <outdir>/drc.lyrdb (KLayout marker DB), drc.log, drc.json, run/ (run_drc.py's own
# files); exit 0 = clean, 1 = violations found, 2 = tool failure.
set -uo pipefail
gds=$(realpath -m "$1"); top=$2; out=$(realpath -m "$3"); thr=${4:-4}; set_=${5:-minimum}
here=$(cd "$(dirname "$0")" && pwd)
pdk=${PDK_ROOT:-/foss/pdks}/ihp-sg13g2
runner=$pdk/libs.tech/klayout/tech/drc/run_drc.py
case "$set_" in
  minimum) opts=(--minimum_drc) ;;
  main) opts=(--disable_extra_rules --no_recommended) ;;
  full) opts=() ;;
  *) echo "unknown ruleset $set_ (minimum|main|full)"; exit 2 ;;
esac
[ "${DENSITY:-0}" = "1" ] || opts+=(--no_density)
[ "${ANTENNA:-0}" = "1" ] && [ "$set_" != "minimum" ] && opts+=(--antenna)
mkdir -p "$out"
rm -rf "$out/run" "$out/drc.lyrdb"
start=$(date +%s.%N)
# --mp 1: one KLayout process at a time; --density_thr is the thread count of every deck.
python3 "$runner" --path="$gds" --topcell="$top" --run_dir="$out/run" --mp=1 \
  --density_thr="$thr" "${opts[@]}" > "$out/drc.log" 2>&1
rc=$?
echo "run_drc.py ${opts[*]} exit=$rc time=$(echo "$(date +%s.%N) - $start" | bc)s" | tee -a "$out/drc.log"
# run_drc.py exits 1 both for violations and for its own errors: trust only its final verdict line
grep -q -e "KLayout DRC Check Passed" -e "Violations were detected" "$out/drc.log" || exit 2
db=$(ls "$out"/run/*_full.lyrdb 2>/dev/null | head -1)
[ -n "$db" ] || db=$(ls "$out"/run/*.lyrdb 2>/dev/null | head -1)
[ -n "$db" ] || exit 2
cp "$db" "$out/drc.lyrdb"
python3 "$here/lyrdb_count.py" "$out/drc.lyrdb" > "$out/drc.json" || exit 2
python3 - "$out/drc.json" "$set_" <<'PY'
import json, sys
p, s = sys.argv[1], sys.argv[2]
d = json.load(open(p)); d["ruleset"] = s
json.dump(d, open(p, "w")); print(json.dumps(d))
PY
total=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["total"])' "$out/drc.json")
[ "$total" = "0" ] && exit 0 || exit 1
