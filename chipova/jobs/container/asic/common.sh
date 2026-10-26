# Shared start-up of the OpenROAD/OpenSTA signoff scripts (sourced, not run).
# signoff_init <inputs_dir> <outdir> <pdk> [top]
#   inputs_dir: a Build ASIC run's final outputs (<top>.def.gz, <top>.vg, <top>.sdc, ...)
#   outdir:     created; every file of the check goes there
#   pdk:        skywater130 | ihp130 | gf180 (or sky130 / sg13g2)
#   top:        default = the name of the only *.def.gz (or *.def) in inputs_dir
# Sets IN OUT TOP DEF, sources pdk_env.sh, checks the PDK files, writes $OUT/pdk_files.json.
# Returns non-zero (the caller exits 2) when an input or a PDK file is missing.

signoff_init() {
  if [ $# -lt 3 ]; then
    echo "usage: $(basename "$0") <inputs_dir> <outdir> <pdk> [top]" >&2
    return 2
  fi
  IN=$(realpath -m "$1"); OUT=$(realpath -m "$2"); TOP=${4:-}
  # shellcheck source=pdk_env.sh
  . "$here/pdk_env.sh" "$3" || return 2
  mkdir -p "$OUT" || return 2
  if [ -z "$TOP" ]; then
    local defs
    defs=$(cd "$IN" && ls *.def.gz *.def 2>/dev/null)
    if [ "$(printf '%s\n' "$defs" | grep -c .)" != "1" ]; then
      echo "give the top cell: inputs_dir has $(printf '%s\n' "$defs" | grep -c .) DEF files" >&2
      return 2
    fi
    TOP=${defs%.gz}; TOP=${TOP%.def}
  fi
  DEF=$IN/$TOP.def.gz
  [ -f "$DEF" ] || DEF=$IN/$TOP.def
  [ -f "$DEF" ] || { echo "no $TOP.def(.gz) in $IN" >&2; return 2; }
  pdk_check_files || return 2
  export IN OUT TOP DEF
  write_pdk_files_json "$OUT/pdk_files.json"
}

# The PDK files of this run, as JSON (also embedded in each check's JSON).
write_pdk_files_json() {
  local c r args=()
  for c in $CORNERS; do
    args+=("corner:$c:$(pdk_get LIB "$c")|$(pdk_get VDD "$c")|$(pdk_get RC "$c")")
  done
  for r in $RC_CORNERS; do
    args+=("rc:$r:$(pdk_get RCX "$r")|$(pdk_get TLEF "$r")")
  done
  python3 -I - "$1" "$PDK_ID" "$TECH_LEF" "$CELL_LEF" "${args[@]}" <<'PY'
import json, sys
path, pdk, tlef, clef, *rest = sys.argv[1:]
out = {"pdk": pdk, "tech_lef": tlef, "cell_lef": clef, "corners": {}, "rc_corners": {}}
for a in rest:
    kind, name, val = a.split(":", 2)
    parts = val.split("|")
    if kind == "corner":
        out["corners"][name] = {"liberty": parts[0], "vdd_v": float(parts[1]), "rc": parts[2]}
    else:
        out["rc_corners"][name] = {"openrcx_rules": parts[0], "tech_lef": parts[1]}
json.dump(out, open(path, "w"), indent=1)
PY
}

# Seconds since a `date +%s.%N` stamp, with millisecond resolution.
elapsed() { python3 -I -c 'import sys,time; print("%.3f" % (time.time() - float(sys.argv[1])))' "$1"; }
