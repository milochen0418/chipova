#!/usr/bin/env bash
# The four OpenROAD/OpenSTA signoff checks of a Build ASIC run, in one container:
#   antenna.sh (check_antennas) -> pex.sh (OpenRCX SPEF per RC corner)
#   -> sta.sh (OpenSTA per corner, on those SPEFs) -> power_ir.sh (report_power + PDNSim per corner)
# usage: signoff_openroad.sh <inputs_dir> <outdir> <pdk> [top]
#   inputs_dir: the run's final outputs (<top>.def.gz, <top>.vg, <top>.sdc, [<top>.typical.spef]);
#   pdk: skywater130 | ihp130 | gf180. The checks' own env options (STA_RC, ACTIVITY, IR_LIMIT_PCT, ...) pass through.
# writes <outdir>/{antenna,pex,sta,power_ir}/ (each check's files and JSON) and signoff_openroad.json;
# prints signoff_openroad.json (one line).
# exit 0 = all four pass, 1 = a check found problems, 2 = a tool failed
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
[ $# -ge 3 ] || { echo "usage: $(basename "$0") <inputs_dir> <outdir> <pdk> [top]" >&2; exit 2; }
in=$1; out=$(realpath -m "$2"); pdk=$3; top=${4:-}
mkdir -p "$out" || exit 2
bash "$here/antenna.sh" "$in" "$out/antenna" "$pdk" $top > "$out/antenna.out" 2>&1; an=$?
bash "$here/pex.sh" "$in" "$out/pex" "$pdk" $top > "$out/pex.out" 2>&1; px=$?
SPEF_DIR=$out/pex bash "$here/sta.sh" "$in" "$out/sta" "$pdk" $top > "$out/sta.out" 2>&1; st=$?
SPEF_DIR=$out/pex bash "$here/power_ir.sh" "$in" "$out/power_ir" "$pdk" $top > "$out/power_ir.out" 2>&1; pw=$?
python3 -I - "$out" "$an" "$px" "$st" "$pw" <<'PY' | tee "$out/signoff_openroad.json"
import json, os, sys
out = sys.argv[1]
codes = dict(zip(("antenna", "pex", "sta", "power_ir"), map(int, sys.argv[2:6])))

def load(name):
    try:
        return json.load(open(os.path.join(out, name, f"{name}.json")))
    except (OSError, ValueError):
        return {}

a, p, s, w = load("antenna"), load("pex"), load("sta"), load("power_ir")
res = {
    "antenna": {"exit": codes["antenna"], "pass": a.get("pass"), "time_s": a.get("time_s"),
                "net_violations": a.get("net_violations"), "pin_violations": a.get("pin_violations"),
                "nets_checked": a.get("routed_signal_nets"), "warnings": a.get("warnings")},
    "pex": {"exit": codes["pex"], "pass": p.get("pass"), "time_s": p.get("time_s"),
            "corners": {k: {"nets": v.get("nets"), "total_cap_pf": v.get("total_cap_pf"),
                            "total_res_ohm": v.get("total_res_ohm"), "rules": v.get("openrcx_rules"),
                            "problems": v.get("problems"), "error": v.get("error")}
                        for k, v in (p.get("corners") or {}).items()}},
    "sta": {"exit": codes["sta"], "pass": s.get("pass"), "time_s": s.get("time_s"), "worst": s.get("worst"),
            "corners": {k: {"setup_ws_ns": (v.get("setup") or {}).get("worst_slack_ns"),
                            "setup_tns_ns": (v.get("setup") or {}).get("tns_ns"),
                            "hold_ws_ns": (v.get("hold") or {}).get("worst_slack_ns"),
                            "hold_tns_ns": (v.get("hold") or {}).get("tns_ns"),
                            "drv_violations": v.get("drv_violations"), "problems": v.get("problems")}
                        for k, v in (s.get("corners") or {}).items()}},
    "power_ir": {"exit": codes["power_ir"], "pass": w.get("pass"), "time_s": w.get("time_s"), "worst": w.get("worst"),
                 "corners": {k: {"power_mw": (v.get("power_mw") or {}).get("total"),
                                 "ir_drop_total_mv": v.get("ir_drop_total_mv"),
                                 "ir_drop_total_pct_of_vdd": v.get("ir_drop_total_pct_of_vdd"),
                                 "problems": v.get("problems"), "warnings": v.get("warnings")}
                             for k, v in (w.get("corners") or {}).items()}},
}
res["clean"] = all(c == 0 for c in codes.values())
print(json.dumps(res))
PY
for c in $an $px $st $pw; do [ "$c" -eq 2 ] && exit 2; done
for c in $an $px $st $pw; do [ "$c" -ne 0 ] && exit 1; done
exit 0
