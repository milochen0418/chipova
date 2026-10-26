# OpenRCX parasitic extraction of a routed DEF for one RC corner -> SPEF.
# env: TLEF (the corner's tech LEF: OpenRCX takes via resistances from it), CELL_LEF, DEF,
#      RULES (the PDK's OpenRCX rules file for the corner), RC (corner name), SPEF (output)
read_lef $::env(TLEF)
read_lef $::env(CELL_LEF)
read_def $::env(DEF)

set routed 0
set unrouted {}
foreach net [[ord::get_db_block] getNets] {
  set type [$net getSigType]
  if { $type == "POWER" || $type == "GROUND" } { continue }
  if { [$net getWire] != "NULL" } {
    incr routed
  } elseif { [llength [$net getITerms]] + [llength [$net getBTerms]] > 1 } {
    lappend unrouted [$net getName]
  }
}
puts "CHIPOVA_SIGNAL_NETS_ROUTED: $routed"
puts "CHIPOVA_SIGNAL_NETS_UNROUTED: [llength $unrouted] [lrange $unrouted 0 19]"

define_process_corner -ext_model_index 0 $::env(RC)
if { [info commands set_extraction_rules_file] != "" } {
  set_extraction_rules_file $::env(RULES)
  extract_parasitics
} else {
  extract_parasitics -ext_model_file $::env(RULES)
}
write_spef $::env(SPEF)
puts "CHIPOVA_SPEF_WRITTEN: $::env(SPEF)"
exit 0
