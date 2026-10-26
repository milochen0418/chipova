# Power (OpenSTA report_power, vectorless or from a VCD) and static IR drop (PDNSim
# analyze_power_grid) of one corner, on the routed DEF with the PDN as routed.
# env: TLEF CELL_LEF DEF LIB SDC SPEF CORNER VDD ACTIVITY ACTIVITY_MODE OUT [VCD VCD_SCOPE]
#      [CUT_LAYERS CUT_RES: cut layers without a resistance in the tech LEF, and ohms per cut]
# PDNSim's voltage sources are the top-level pins of each supply net in the DEF (Build ASIC puts
# them on the top PDN layer); every supply net's voltage is set explicitly (VDD / 0 V), never
# taken from a liberty file.
read_lef $::env(TLEF)
read_lef $::env(CELL_LEF)
read_def $::env(DEF)
# PDNSim takes a via's resistance from its cut layer; a tech LEF that gives it per VIA only
# (GF180's) leaves the layer at 0 ("Via1 has zero resistance"): set from the PDK's values.
if { [info exists ::env(CUT_RES)] && $::env(CUT_RES) != "" } {
  foreach name $::env(CUT_LAYERS) {
    set layer [[ord::get_db_tech] findLayer $name]
    if { $layer != "NULL" && [$layer getResistance] == 0 } {
      $layer setResistance $::env(CUT_RES)
      puts "CHIPOVA_CUT_RES: $name $::env(CUT_RES)"
    }
  }
}
read_liberty $::env(LIB)
read_sdc $::env(SDC)
set_propagated_clock [all_clocks]
read_spef $::env(SPEF)

set c $::env(CORNER)
set o $::env(OUT)

if { [info exists ::env(VCD)] && $::env(VCD) != "" } {
  read_vcd -scope $::env(VCD_SCOPE) $::env(VCD)
  puts "CHIPOVA_ACTIVITY: vcd $::env(VCD) scope $::env(VCD_SCOPE)"
} elseif { $::env(ACTIVITY_MODE) == "input" } {
  # Only the primary inputs; OpenSTA propagates through logic, but not around register loops
  # (a counter's flops then get activity 0).
  set_power_activity -input -activity $::env(ACTIVITY) -duty 0.5
  puts "CHIPOVA_ACTIVITY: vectorless -input -activity $::env(ACTIVITY) -duty 0.5"
} else {
  # Every non-clock pin toggles ACTIVITY times per clock cycle; clock nets follow their clocks.
  set_power_activity -global -activity $::env(ACTIVITY) -duty 0.5
  puts "CHIPOVA_ACTIVITY: vectorless -global -activity $::env(ACTIVITY) -duty 0.5"
}
report_activity_annotation > $o/power_$c.activity.rpt
report_power -digits 6 > $o/power_$c.rpt
report_power -format json -digits 6 > $o/power_$c.json
puts "CHIPOVA_POWER_DONE: $c"

set power_nets {}
set ground_nets {}
foreach net [[ord::get_db_block] getNets] {
  set t [$net getSigType]
  if { $t == "POWER" } { lappend power_nets [$net getName] }
  if { $t == "GROUND" } { lappend ground_nets [$net getName] }
}
puts "CHIPOVA_SUPPLY_NETS: power {$power_nets} ground {$ground_nets}"
foreach n $power_nets { set_pdnsim_net_voltage -net $n -voltage $::env(VDD) }
foreach n $ground_nets { set_pdnsim_net_voltage -net $n -voltage 0 }

foreach n [concat $power_nets $ground_nets] {
  set bpins 0
  set bterm [[ord::get_db_block] findBTerm $n]
  if { $bterm != "NULL" } { set bpins [llength [$bterm getBPins]] }
  puts "CHIPOVA_IR_NET: $n pins $bpins"
  if { [catch {
    analyze_power_grid -net $n -voltage_file $o/ir_${c}_$n.csv -error_file $o/ir_${c}_$n.errors \
      -enable_em -em_outfile $o/em_${c}_$n.csv
  } err] } {
    puts "CHIPOVA_IR_ERROR: $n $err"
  } else {
    puts "CHIPOVA_IR_DONE: $n"
  }
}
exit 0
