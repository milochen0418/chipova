# Render a GDS/OASIS layout to PNG with KLayout in batch mode.
# usage: klayout -zz -r gds_png.py -rd gds=<in.gds[.gz]> -rd png=<out.png>
#                [-rd lyp=<layer props .lyp>] [-rd size=2048] [-rd hide=81/4,235/4]
# (-rd values arrive as Python globals; the PDK .lyp gives the usual colours,
#  e.g. $PDK_ROOT/sky130A/libs.tech/klayout/tech/sky130A.lyp)
import pya

g = globals()
size = int(g.get("size", "2048"))
view = pya.LayoutView()
view.load_layout(g["gds"], True)
if g.get("lyp"):
    view.load_layer_props(g["lyp"])
hide = [h for h in g.get("hide", "").split(",") if h]
it = view.begin_layers()
while not it.at_end():
    lp = it.current()
    if f"{lp.source_layer}/{lp.source_datatype}" in hide:
        lp.visible = False
        view.set_layer_properties(it, lp)
    it.next()
view.max_hier()
view.set_config("background-color", "#ffffff")
view.set_config("grid-visible", "false")
view.set_config("text-visible", "false")
view.zoom_fit()
view.save_image(g["png"], size, size)
print(f"wrote {g['png']} ({size}x{size})")
