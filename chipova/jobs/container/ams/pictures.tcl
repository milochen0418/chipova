# Draws every schematic (.sch) and symbol (.sym) of a project as SVG and PNG with xschem.
#
# Needs an X display for complete pictures (text extents) and for PNG at all, so run it as:
#   xvfb-run -a xschem -r -q --tcl "set dark_colorscheme 0" --rcfile <project xschemrc> \
#       --script pictures.tcl
# Without X (xschem -x) the SVG is still drawn, but texts outside the wires' and symbols'
# bounding box are clipped and there is no PNG (set PICTURES_PNG=0 then).
#
# Environment (all optional):
#   PICTURES_SRC   the project folder              (default /work/src)
#   PICTURES_DIRS  its folders to draw, ":"-separated (default xschem:cace/templates)
#   PICTURES_OUT   where the pictures go          (default /work/out/pictures)
#   PICTURES_PNG   1 = also PNG (needs X), 0 = SVG only
#   PICTURES_WIDTH PNG width in pixels (the height follows the drawing; default 1600)
#   PICTURES_MARGIN extra border around xschem's bounding box, as a fraction (default 0.04):
#                  xschem's box is a little short of long monospace text lines
# Picture names: <folder with / as _>__<file name>.svg / .png, e.g. xschem__inverter.svg,
# xschem__inverter.sym.svg (symbols keep .sym so they don't clash with their schematic).

proc env_or {name default} {
  if {[info exists ::env($name)] && $::env($name) ne {}} { return $::env($name) }
  return $default
}

set src  [env_or PICTURES_SRC /work/src]
set dirs [split [env_or PICTURES_DIRS xschem:cace/templates] :]
set out  [env_or PICTURES_OUT /work/out/pictures]
set png  [env_or PICTURES_PNG 1]
set png_w  [env_or PICTURES_WIDTH 1600]
set margin [env_or PICTURES_MARGIN 0.04]
file mkdir $out

set made 0
set failed 0
foreach dir $dirs {
  set files [lsort [concat [glob -nocomplain -directory [file join $src $dir] -types f *.sch] \
                           [glob -nocomplain -directory [file join $src $dir] -types f *.sym]]]
  foreach f $files {
    set tail [file tail $f]
    if {[file extension $tail] eq ".sch"} { set tail [file rootname $tail] }
    set name "[string map {/ _} $dir]__$tail"
    if {[catch {
      xschem load $f
      xschem zoom_full
      # The area to draw: xschem's bounding box plus a margin (an explicit area keeps texts
      # that end a little past the box). The PNG height follows the drawing's aspect ratio.
      lassign [xschem get bbox] x1 y1 x2 y2
      set mx [expr {($x2 - $x1) * $margin}]
      set my [expr {($y2 - $y1) * $margin}]
      set area [list [expr {$x1 - $mx}] [expr {$y1 - $my}] [expr {$x2 + $mx}] [expr {$y2 + $my}]]
      lassign $area ax1 ay1 ax2 ay2
      set png_h [expr {max(100, min(4 * $png_w, round($png_w * ($ay2 - $ay1) / ($ax2 - $ax1))))}]
      xschem print svg [file join $out $name.svg] 0 0 {*}$area
      if {$png} { xschem print png [file join $out $name.png] $png_w $png_h {*}$area }
    } msg]} {
      puts "pictures: FAILED $f: $msg"
      incr failed
      continue
    }
    if {![file exists [file join $out $name.svg]]} {
      puts "pictures: FAILED $f: no SVG written"
      incr failed
      continue
    }
    puts "pictures: $f -> $name.svg[expr {$png ? " + $name.png" : ""}]"
    incr made
  }
}
puts "pictures: $made drawn, $failed failed"
