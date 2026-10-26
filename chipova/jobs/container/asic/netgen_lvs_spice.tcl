# netgen LVS: extracted layout SPICE vs. a SPICE schematic that already holds the cells' .SUBCKTs
# (vg2spice.py output). env: LAYOUT_SPICE, NETLIST_SPICE, TOP, SETUP, REPORT
set circuit1 [readnet spice $::env(LAYOUT_SPICE)]
set circuit2 [readnet spice $::env(NETLIST_SPICE)]
lvs "$circuit1 $::env(TOP)" "$circuit2 $::env(TOP)" $::env(SETUP) $::env(REPORT) -json
