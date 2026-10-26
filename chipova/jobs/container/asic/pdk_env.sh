# PDK files and analysis corners for the OpenROAD/OpenSTA signoff scripts (sourced, not run).
# usage: . pdk_env.sh <pdk>     pdk: skywater130 | sky130 | sky130A | ihp130 | sg13g2 | ihp-sg13g2 | gf180
#
# Sets:
#   PDK_ID                    skywater130 | ihp130 | gf180 (Chipova's ids)
#   CELL_LEF                  standard-cell LEF (the one Build ASIC used)
#   TECH_LEF                  nominal tech LEF (the one Build ASIC used; antenna rules, PDN resistance)
#   CORNERS                   "slow typical fast" (Build ASIC's three timing scenes)
#   LIB_<c> VDD_<c> RC_<c>    per corner: liberty, supply voltage (V), RC corner it is timed with
#   RC_CORNERS                RC corners to extract
#   RCX_<r> TLEF_<r>          per RC corner: OpenRCX rules file, tech LEF (its via resistances are
#                             what OpenRCX uses for vias; SKY130 ships min/nom/max tech LEFs)
#   DIODE_CELL                the PDK's antenna diode cell (reported, not inserted)
#   CUT_LAYERS CUTRES_<r>     cut layers the tech LEF gives no resistance (GF180's gives it per VIA
#                             only, PDNSim reads the layer's) and their ohms per cut per RC corner
# Any of these may be set in the environment beforehand to override the default.
# All paths are inside chipova/eda-osic:2026.10-3 (IIC-OSIC-TOOLS 2026.10 + SiliconCompiler data).

_pdk=$(printf '%s' "${1:-}" | tr 'A-Z' 'a-z')
_sc_root=${SC_DATAROOT:-/opt/sc-cache/dataroot}
_lp=$(ls -d "$_sc_root"/lambdapdk-*/lambdapdk 2>/dev/null | head -1)
_pdk_root=${PDK_ROOT:-/foss/pdks}

case "$_pdk" in
  skywater130|sky130|sky130a)
    PDK_ID=skywater130
    _hd=$_lp/sky130/libs/sky130hd
    _tl=$_pdk_root/sky130A/libs.ref/sky130_fd_sc_hd/techlef
    _rcx=$_pdk_root/sky130A/libs.tech/librelane
    : "${TECH_LEF:=$_lp/sky130/base/apr/sky130_fd_sc.tlef}"          # = sky130_fd_sc_hd__nom.tlef
    : "${CELL_LEF:=$_hd/lef/sky130_fd_sc_hd_merged.lef}"
    : "${CORNERS:=slow typical fast}"
    : "${LIB_slow:=$_hd/nldm/sky130_fd_sc_hd__ss_n40C_1v40.lib.gz}"
    : "${LIB_typical:=$_hd/nldm/sky130_fd_sc_hd__tt_025C_1v80.lib.gz}"
    : "${LIB_fast:=$_hd/nldm/sky130_fd_sc_hd__ff_100C_1v95.lib.gz}"
    : "${VDD_slow:=1.40}" "${VDD_typical:=1.80}" "${VDD_fast:=1.95}"
    # open_pdks' OpenRCX decks calibrated against Calibre (LibreLane's default for sky130A), with
    # the matching min/nom/max tech LEFs.
    : "${RC_CORNERS:=min nom max}"
    : "${RC_slow:=max}" "${RC_typical:=nom}" "${RC_fast:=min}"
    : "${RCX_min:=$_rcx/rules.openrcx.sky130A.min.calibre}"
    : "${RCX_nom:=$_rcx/rules.openrcx.sky130A.nom.calibre}"
    : "${RCX_max:=$_rcx/rules.openrcx.sky130A.max.calibre}"
    : "${TLEF_min:=$_tl/sky130_fd_sc_hd__min.tlef}"
    : "${TLEF_nom:=$TECH_LEF}"
    : "${TLEF_max:=$_tl/sky130_fd_sc_hd__max.tlef}"
    : "${DIODE_CELL:=sky130_fd_sc_hd__diode_2}"
    ;;
  ihp130|sg13g2|ihp-sg13g2)
    PDK_ID=ihp130
    # SiliconCompiler's ihp130 data root (/opt/sc-cache/dataroot/ihp130-*) is a symlink to /foss/pdks.
    _ihp=$_pdk_root/ihp-sg13g2
    _sc=$_ihp/libs.ref/sg13g2_stdcell
    : "${TECH_LEF:=$_sc/lef/sg13g2_tech.lef}"
    : "${CELL_LEF:=$_sc/lef/sg13g2_stdcell.lef}"
    : "${CORNERS:=slow typical fast}"
    : "${LIB_slow:=$_sc/lib/sg13g2_stdcell_slow_1p35V_125C.lib}"
    : "${LIB_typical:=$_sc/lib/sg13g2_stdcell_typ_1p50V_25C.lib}"
    : "${LIB_fast:=$_sc/lib/sg13g2_stdcell_fast_1p65V_m40C.lib}"
    : "${VDD_slow:=1.35}" "${VDD_typical:=1.50}" "${VDD_fast:=1.65}"
    # IHP's own OpenRCX deck, "generated using proprietary reference extractor" (LibreLane's
    # default; SiliconCompiler's typical.rules extracts identically). IHP ships no min/max deck
    # from that extractor (its *.magic.rules are "if you feel lucky"), so every corner uses it.
    : "${RC_CORNERS:=nom}"
    : "${RC_slow:=nom}" "${RC_typical:=nom}" "${RC_fast:=nom}"
    : "${RCX_nom:=$_ihp/libs.tech/librelane/openrcx/IHP_rcx_patterns.rules}"
    : "${TLEF_nom:=$TECH_LEF}"
    : "${DIODE_CELL:=sg13g2_antennanp}"
    ;;
  gf180|gf180mcu|gf180mcuc)
    PDK_ID=gf180
    # What SiliconCompiler's gf180_demo target builds with (lambdapdk GF180_5LM_1TM_9K_9t): 5
    # metals with a 9 kA top metal, the 9-track 5 V cells, and lambdapdk's OpenRCX decks for that
    # stack (MIM option B), worst / typical / best as max / nom / min, all with the one tech LEF.
    _gf=$_lp/gf180
    _sc=$_gf/libs/gf180mcu_fd_sc_mcu9t5v0
    _rules=$_gf/base/pex/openroad/gf180mcu_1p5m_1tm_9k_sp_smim_OPTB
    : "${TECH_LEF:=$_gf/base/apr/gf180mcu_5LM_1TM_9K_9t_tech.lef}"
    : "${CELL_LEF:=$_sc/lef/gf180mcu_fd_sc_mcu9t5v0.lef}"
    : "${CORNERS:=slow typical fast}"
    : "${LIB_slow:=$_sc/nldm/gf180mcu_fd_sc_mcu9t5v0__ss_125C_4v50.lib.gz}"
    : "${LIB_typical:=$_sc/nldm/gf180mcu_fd_sc_mcu9t5v0__tt_025C_5v00.lib.gz}"
    : "${LIB_fast:=$_sc/nldm/gf180mcu_fd_sc_mcu9t5v0__ff_n40C_5v50.lib.gz}"
    : "${VDD_slow:=4.50}" "${VDD_typical:=5.00}" "${VDD_fast:=5.50}"
    : "${RC_CORNERS:=min nom max}"
    : "${RC_slow:=max}" "${RC_typical:=nom}" "${RC_fast:=min}"
    : "${RCX_min:=${_rules}_bst.rules}"
    : "${RCX_nom:=${_rules}_typ.rules}"
    : "${RCX_max:=${_rules}_wst.rules}"
    : "${TLEF_min:=$TECH_LEF}" "${TLEF_nom:=$TECH_LEF}" "${TLEF_max:=$TECH_LEF}"
    : "${DIODE_CELL:=gf180mcu_fd_sc_mcu9t5v0__antenna}"
    # lambdapdk's via resistance (the same for every gf180 stack): best / typical / worst.
    : "${CUT_LAYERS:=Via1 Via2 Via3 Via4}"
    : "${CUTRES_min:=4.23}" "${CUTRES_nom:=4.5}" "${CUTRES_max:=16.845}"
    ;;
  *)
    echo "pdk_env.sh: unknown PDK '${1:-}' (skywater130 | ihp130 | gf180)" >&2
    return 2 2>/dev/null || exit 2
    ;;
esac
export PDK_ID TECH_LEF CELL_LEF CORNERS RC_CORNERS DIODE_CELL CUT_LAYERS

# Indirect lookups: pdk_get LIB slow -> $LIB_slow
pdk_get() { local v="${1}_${2}"; printf '%s' "${!v:-}"; }

# Every file named above must exist, or the run is a tool failure (exit 2 by the caller).
pdk_check_files() {
  local missing=0 c r f
  for f in "$TECH_LEF" "$CELL_LEF"; do [ -f "$f" ] || { echo "missing PDK file: $f" >&2; missing=1; }; done
  for c in $CORNERS; do
    f=$(pdk_get LIB "$c"); [ -f "$f" ] || { echo "missing liberty for $c: $f" >&2; missing=1; }
  done
  for r in $RC_CORNERS; do
    for f in "$(pdk_get RCX "$r")" "$(pdk_get TLEF "$r")"; do
      [ -f "$f" ] || { echo "missing RC file for $r: $f" >&2; missing=1; }
    done
  done
  return $missing
}
