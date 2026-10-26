# netgen LVS: extracted layout SPICE vs. gate-level Verilog (+ std-cell SPICE as cell views).
# env: LAYOUT_SPICE, NETLIST_V, CELL_SPICE, TOP, SETUP, REPORT
set circuit1 [readnet spice $::env(LAYOUT_SPICE)]
set circuit2 [readnet verilog /dev/null]
readnet spice $::env(CELL_SPICE) $circuit2
readnet verilog $::env(NETLIST_V) $circuit2
lvs "$circuit1 $::env(TOP)" "$circuit2 $::env(TOP)" $::env(SETUP) $::env(REPORT) -blackbox -json
