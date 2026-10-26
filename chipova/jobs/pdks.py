"""The PDKs Chipova knows (the blueprint's PDK registry): what Build ASIC targets for each, and
which signoff checks are set up for it here.

Only what was verified in the IIC-OSIC-TOOLS profile is marked as working: SKY130 runs RTL to
GDSII offline with KLayout and Magic DRC and Magic/Netgen LVS; IHP SG13G2 runs RTL to GDSII, its
signoff decks are in the image but not set up in Chipova yet; GF180's SiliconCompiler data isn't
baked into the profile. None of these results is a foundry's signoff.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pdk:
    id: str  # what chipova.toml's [asic] pdk says
    title: str
    sc_target: str  # sc_flow.py --pdk
    lyp: str  # the PDK's KLayout layer colours, in the image
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
        flow=True,
        drc="",
        lvs="",
        status="The open IHP SG13G2 PDK, for IHP's open MPW shuttles; its DRC/LVS decks aren't set up in Chipova yet.",
    ),
    "gf180": Pdk(
        id="gf180",
        title="GlobalFoundries GF180MCU",
        sc_target="gf180",
        lyp="/foss/pdks/gf180mcuD/libs.tech/klayout/tech/gf180mcu.lyp",
        flow=False,
        drc="",
        lvs="",
        status="SiliconCompiler's GF180 data isn't baked into the IIC-OSIC-TOOLS profile yet.",
    ),
}


def get(pdk_id: str) -> Pdk | None:
    return PDKS.get((pdk_id or "").strip().lower())
