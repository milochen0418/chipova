# OpenROAD antenna rule check of a routed DEF (process antenna effect, the tech LEF's ANTENNA* rules
# against the cell LEF's ANTENNAGATEAREA / ANTENNADIFFAREA).
# env: TECH_LEF CELL_LEF DEF OUT
read_lef $::env(TECH_LEF)
read_lef $::env(CELL_LEF)
read_def $::env(DEF)

# What gets checked: routed signal nets (power/ground nets have no gates to protect).
set routed 0
set unrouted 0
foreach net [[ord::get_db_block] getNets] {
  set type [$net getSigType]
  if { $type == "POWER" || $type == "GROUND" } { continue }
  if { [$net getWire] != "NULL" } {
    incr routed
  } elseif { [llength [$net getITerms]] + [llength [$net getBTerms]] > 1 } {
    incr unrouted
  }
}
puts "CHIPOVA_SIGNAL_NETS_ROUTED: $routed"
puts "CHIPOVA_SIGNAL_NETS_UNROUTED: $unrouted"

set nets [check_antennas -report_file $::env(OUT)/antenna.rpt]
puts "CHIPOVA_ANTENNA_NETS: $nets"
exit 0
