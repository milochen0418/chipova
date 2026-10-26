# Analog/mixed-signal chip on IHP SG13G2

This project is JKU's [ihp-sg13g2-ams-chip-template](https://github.com/iic-jku/ihp-sg13g2-ams-chip-template)
(release 2026.09, commit `cf12265`), © 2026 Simon Dorrer and Harald Pretl, under Apache-2.0 WITH
SHL-2.1 (each file says so in its header). The chip is 1.6 mm × 1.6 mm: a counter (digital,
hardened with LibreLane) and an inverter (analog, drawn by hand) in a padframe of 32 IO cells with
a seal ring.

## What is here, and what isn't

Here are the files you change: the chip's RTL (`rtl/`), its LibreLane setup (`flow/librelane/`),
the counter's RTL, LibreLane setup and testbenches (`macros/counter/`), the Xschem schematics of
the inverter and of the chip (`macros/inverter/schematic/`, `schematic/`) and the chip's cocotb
testbench (`testbenches/cocotb/`).

Everything else (the Makefiles and scripts, the IO cells, the inverter's layout, the bondpad and
logo sources) comes with Chipova's IIC-OSIC-TOOLS image (`/opt/chipova/ams-template`). A **Full
chip** run copies that tree, puts this snapshot's files over it, deletes every generated file
(`make clean-all`) and builds from there.

## What Full chip runs

1. The bondpad and the two logos, with their KLayout and Magic DRC.
2. The counter: LibreLane with Magic and KLayout DRC, LVS and antenna checks.
3. The inverter: KLayout and Magic DRC and LVS, then its LEF and views.
4. The chip: LibreLane's chip flow (padframe, power grid, placement and routing, seal ring,
   gate-level LVS with the macros as black boxes), its reports, GDS and netlists.
5. Magic DRC of the whole chip, and the chip's cocotb simulations (RTL and gate level).

## What it can't say yet

The **Full chip** signoff check never reads PASS today:

- The template's top-level LVS (the chip's layout against its Xschem schematic) isn't finished
  upstream, so only LibreLane's gate-level LVS runs.
- The logo and metal fill, and the DRC of the filled chip, need more memory than a run gets here.
- The template's authors report 219 items of IHP's regular DRC on their filled chip (recommended
  pad rules and 10 `NW.d`).

So the check is FAIL when something that ran failed, and otherwise BLOCKED with these reasons.
Chipova's own **Lint** and **Simulate** work on the counter (`chipova.toml`).
