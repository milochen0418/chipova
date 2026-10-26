# Magic LVS extraction (sky130A). env: GDS (full-layout GDS), TOP, OUT (dir), CELL_SPICE (std-cell
# spice, used only to annotate port order).
crashbackups disable
locking disable
drc off
gds read $::env(GDS)
readspice $::env(CELL_SPICE)
load $::env(TOP) -dereference
cd $::env(OUT)
extract do local
extract no capacitance
extract no coupling
extract no resistance
extract no adjust
extract unique
extract
ext2spice lvs
ext2spice -o $::env(OUT)/$::env(TOP).spice $::env(TOP).ext
quit -noprompt
