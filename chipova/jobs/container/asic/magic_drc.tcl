# Magic DRC (sky130A). env: GDS (full-layout GDS), TOP, OUT (dir for reports)
# run: magic -dnull -noconsole -rcfile $PDK_ROOT/sky130A/libs.tech/magic/sky130A.magicrc magic_drc.tcl
crashbackups disable
locking disable
gds read $::env(GDS)
load $::env(TOP) -dereference
select top cell
drc euclidean on
drc style drc(full)
drc on
drc check
drc catchup
set oscale [cif scale out]
set fout [open $::env(OUT)/magic_drc.rpt w]
set count 0
foreach {why boxes} [drc listall why] {
    puts $fout $why
    puts $fout "----------------------------------------"
    foreach b $boxes {
        puts $fout [format "  %.3f %.3f %.3f %.3f um" \
            [expr {$oscale * [lindex $b 0]}] [expr {$oscale * [lindex $b 1]}] \
            [expr {$oscale * [lindex $b 2]}] [expr {$oscale * [lindex $b 3]}]]
        incr count
    }
}
puts $fout "TOTAL $count"
close $fout
puts "MAGIC_DRC_COUNT: $count"
quit -noprompt
