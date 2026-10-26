#!/usr/bin/env bash
# Magic DRC for IHP SG13G2 (the PDK's ihp-sg13g2.magicrc, style drc(full)); same magic_drc.tcl
# as the SKY130 Magic DRC. usage: drc_ihp_magic.sh <layout.gds|.gds.gz> <topcell> <outdir>
# The GDS must hold the real std-cell layouts (SC's IHP output does).
# writes <outdir>/magic_drc.rpt, magic_drc.log, magic_drc.json; exit 0 = clean, 1 = violations,
# 2 = failure
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
gds=$(realpath -m "$1"); top=$2; out=$(realpath -m "$3")
pdk=${PDK_ROOT:-/foss/pdks}/ihp-sg13g2
mkdir -p "$out"
export GDS=$gds TOP=$top OUT=$out
start=$(date +%s.%N)
(cd "$out" && magic -dnull -noconsole -rcfile "$pdk/libs.tech/magic/ihp-sg13g2.magicrc" \
  "$here/magic_drc.tcl" < /dev/null > magic_drc.log 2>&1)
rc=$?
echo "magic exit=$rc time=$(echo "$(date +%s.%N) - $start" | bc)s" | tee -a "$out/magic_drc.log"
n=$(sed -n 's/^MAGIC_DRC_COUNT: //p' "$out/magic_drc.log" | tail -1)
[ -n "$n" ] || exit 2
echo "{\"total\": $n}" | tee "$out/magic_drc.json"
[ "$n" = "0" ] && exit 0 || exit 1
