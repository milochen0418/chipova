"""The PDKs Chipova knows (the blueprint's PDK registry): what Build ASIC targets for each, and
which signoff checks are set up for it here.

Only what was verified in the IIC-OSIC-TOOLS profile is marked as working: all three run RTL to
GDSII offline (GF180 since its SiliconCompiler data is baked into chipova/eda-osic:2026.10-3), with
each PDK's own open DRC and LVS decks: SKY130 KLayout + Magic DRC and Magic/Netgen LVS; IHP
SG13G2 its KLayout DRC and LVS decks + Magic DRC; GF180 the open_pdks KLayout DRC deck and
Magic/Netgen LVS. None of these results is a foundry's signoff.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pdk:
    id: str  # what chipova.toml's [asic] pdk says
    title: str
    sc_target: str  # sc_flow.py --pdk
    lyp: str  # the PDK's KLayout layer colours, in the image
    folder: str  # its folder under /foss/pdks (Xschem, ngspice, CACE: $PDK)
    flow: bool  # Build ASIC works offline in the profile
    drc: str  # "" = no DRC deck set up here
    lvs: str  # "" = no LVS set up here
    status: str  # what its maker says it is


PDKS: dict[str, Pdk] = {
    "skywater130": Pdk(
        id="skywater130",
        title="SkyWater SKY130 (sky130A, sky130_fd_sc_hd)",
        sc_target="sky130",
        lyp="/foss/pdks/sky130A/libs.tech/klayout/tech/sky130A.lyp",
        folder="sky130A",
        flow=True,
        drc="sky130A_mr.drc (KLayout) + Magic sky130A",
        lvs="Magic extraction + Netgen sky130A_setup.tcl",
        status="SkyWater calls the open SKY130 PDK an experimental preview: not qualified for production.",
    ),
    "ihp130": Pdk(
        id="ihp130",
        title="IHP SG13G2 (130 nm SiGe BiCMOS)",
        sc_target="ihp130",
        lyp="/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/sg13g2.lyp",
        folder="ihp-sg13g2",
        flow=True,
        drc="IHP ihp-sg13g2.drc, main rule set (KLayout; holds the foundry precheck's minimum rules) + Magic ihp-sg13g2",
        lvs="IHP sg13g2.lvs (KLayout, hierarchical) against the gate-level netlist",
        status="The open IHP SG13G2 PDK, for IHP's open MPW shuttles.",
    ),
    "gf180": Pdk(
        id="gf180",
        title="GlobalFoundries GF180MCU",
        sc_target="gf180",
        lyp="/foss/pdks/gf180mcuD/libs.tech/klayout/tech/gf180mcu.lyp",
        folder="gf180mcuD",
        flow=True,
        drc="open_pdks gf180mcu.drc, variant C = the 9 kÅ top metal Build ASIC makes (KLayout; antenna and density apart)",
        lvs="Magic extraction + Netgen gf180mcuD_setup.tcl",
        status="GlobalFoundries' open GF180MCU PDK (the open_pdks gf180mcuD decks in the image).",
    ),
}


def get(pdk_id: str) -> Pdk | None:
    return PDKS.get((pdk_id or "").strip().lower())
