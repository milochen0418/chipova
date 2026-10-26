# Third-party notices

Chipova's own code is under the MIT license ([LICENSE](LICENSE)). It uses libraries, runs tools
and reads PDK data that are under their own licenses, listed here as they were read on
2026-10-26 (from the installed packages' metadata, the files inside the tool images, and the
upstream repositories). The full inventory, with versions, is the CycloneDX SBOM
[docs/sbom/chipova.cdx.json](docs/sbom/chipova.cdx.json) (`poetry run python scripts/sbom.py`
writes it again). This list is a record of what is used, not legal advice.

## Code copied into Chipova

`assets/chipova/collab.js` contains a version of **y-monaco** 0.1.6's `MonacoBinding` and of
**lib0**'s mutex, adapted to use the page's `window.monaco`:

```
The MIT License (MIT)

Copyright (c) 2019 Kevin Jahns <kevin.jahns@protonmail.com>.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

(lib0 carries the same MIT notice, same author.)

## Python packages (installed with Poetry)

| Package | Version | License |
|---|---|---|
| reflex | 0.10.0 | Apache-2.0 |
| reflex-monaco | 0.0.3 | Apache-2.0 |
| pycrdt | 0.14.10 | MIT |
| docker (docker-py) | 7.2.0 | Apache-2.0 |
| klayout | 0.30.12 | GPL-3.0-or-later (see the note below) |
| pydantic | 2.14.1 | MIT |
| PyJWT | 2.15.1 | MIT |
| starlette (with Reflex) | 1.10.0 | BSD-3-Clause |
| granian (with Reflex) | 2.8.5 | BSD-3-Clause |
| reflex-ddns-auth | 0.1.0 | the re-ddns platform's own library (same author) |
| pytest, pytest-asyncio, playwright (development only) | 9.1.1, 1.4.1, 1.64.1 | MIT, Apache-2.0, Apache-2.0 |

The packages these bring in (62 in the environment in all) are in the SBOM with their licenses.

**klayout** is imported by Chipova's layout worker (`chipova/jobs/layout_worker.py`, a separate
process) to draw layouts. Chipova's source is MIT; whoever distributes Chipova together with
klayout (for example in one container image) distributes klayout under the GPL-3.0's terms.

## Browser

Bundled by Reflex into the frontend (npm): react 19.3.0, react-dom, react-router 8.4.0,
@radix-ui/themes 3.3.0, @monaco-editor/react 4.7.0, recharts 3.10.1, socket.io-client 4.8.4,
sonner 2.0.8, yjs 13.6.18, y-websocket 2.0.4 (all MIT), lucide-react 1.26.0 (ISC), and the others
in the SBOM. monaco-editor 0.55.1 (MIT) is installed with them and its files are served by
Chipova's backend (`/_chipova/monaco/0.55.1/`); nothing is loaded from a CDN.

The Xschem desktop page is noVNC (core library MPL-2.0, © The noVNC authors) from the IIC-OSIC
image, passed through Chipova's backend unchanged.

## Tool images (built on your machine)

Chipova doesn't ship images: **Tools & settings** builds them on your Docker from the Dockerfiles in
`infra/dockerfiles`, on public bases pinned by digest. What they contain comes under its own
licenses.

**`chipova/eda-base:1`**: Debian 13 (`debian:trixie-slim@sha256:62bd423a…`) and Debian's packages
(licenses from each package's `/usr/share/doc/<package>/copyright` in the image):

| Tool | Debian package version | License |
|---|---|---|
| Icarus Verilog | 12.0 | GPL-2.0-or-later (parts MIT) |
| Verilator | 5.032 | LGPL-3.0-only or Artistic-2.0 |
| Yosys | 0.52 | ISC |
| nextpnr-ice40, nextpnr-ecp5, nextpnr-gowin | 0.7 | ISC (parts BSD-3-Clause) |
| Project IceStorm | (Debian's) | ISC (parts GPL-2.0-or-later, MIT) |
| Project Trellis (fpga-trellis, ECP5) | 1.4 | ISC (parts BSD-3-Clause) |
| apicula (python3-apycula, Gowin) | 0.17 | MIT (parts ISC) |
| ngspice | 44.2 | BSD-3-Clause (parts CC-BY-SA-4.0, public domain) |
| Graphviz | 2.42.4 | EPL-1.0 (parts MIT, zlib-style) |

plus the Debian base system (234 packages in all, listed in the SBOM).

**`chipova/eda-osic:2026.10-3`**: [IIC-OSIC-TOOLS](https://github.com/iic-jku/IIC-OSIC-TOOLS)
2026.10 (`hpretl/iic-osic-tools@sha256:306585de…`; its build scripts: Apache-2.0, © Department for
Integrated Circuits, Johannes Kepler University Linz), an Ubuntu-based image of many tools (1,555
packages and the `/foss/tools` builds; see the SBOM). Those Chipova runs:

| Tool | Version | License |
|---|---|---|
| SiliconCompiler | 0.38.10 | Apache-2.0 |
| lambdapdk (PDK data SiliconCompiler builds with: SKY130, IHP 130, GF180) | 0.2.22 | Apache-2.0 (© Zero ASIC Corporation) |
| OpenROAD | 26Q4-407-geb14e40b7 | BSD-3-Clause (© The OpenROAD Authors) |
| Yosys | 0.70 | ISC |
| KLayout | 0.30.12 | GPL-3.0-or-later |
| Magic | 8.3.685 | BSD-style permissive (© Regents of the University of California) |
| Netgen | 1.5.324 | GNU GPL (its `Copying` file is the GPL version 1 text) |
| ngspice, Verilator, Icarus Verilog | 47, 5.052, 14.0 (devel) | as above |
| CACE | 2.11.0 | Apache-2.0 |
| Xschem | 3.4.8RC | GPL-2.0-or-later (© Stefan Schippers) |
| TigerVNC, websockify, Xvfb (the desktops) | Ubuntu's | GPL-2.0-or-later; LGPL-3.0; MIT/X11 |

The image also holds JKU's [ihp-sg13g2-ams-chip-template](https://github.com/iic-jku/ihp-sg13g2-ams-chip-template)
release 2026.09 (`cf12265`; © 2026 Simon Dorrer and Harald Pretl; Apache-2.0 WITH SHL-2.1), cloned
when the image is built, without EUROPRACTICE's package drawings (`LicenseRef-EUROPRACTICE`, not
under the template's licence) and without the `flow/artistic` submodule.

The tools run as separate programs in containers; Chipova doesn't link them.

**On your own computers** (not in Chipova): the board helper calls
[openFPGALoader](https://github.com/trabucayre/openFPGALoader) (Apache-2.0), which you install; the
Heartbeat's bench script uses [OpenHTF](https://github.com/google/openhtf) (Apache-2.0).

## PDKs

| PDK | Version (in the image) | License | Note |
|---|---|---|---|
| SkyWater SKY130 (sky130A, via open_pdks) | open_pdks `1689ac3f2dc7` | Apache-2.0 | SkyWater calls it an experimental preview: not a guarantee of manufacturability |
| GlobalFoundries GF180MCU (gf180mcuD) | open_pdks `1689ac3f2dc7` (decks), lambdapdk 0.2.22 (Build ASIC) | Apache-2.0 | |
| IHP SG13G2 | `a49358cc0b20` (IHP-Open-PDK) | Apache-2.0 | |

Open PDKs are published for anyone to use; whether a foundry accepts a design made with one for
manufacturing is the foundry's decision, under its own terms. Chipova doesn't support commercial
or NDA PDKs, and doesn't send PDK data anywhere.

## Templates

The project templates (`templates/`) were written for Chipova and are under its MIT license,
except `ams_chip_ihp`, whose files are copies of JKU's chip template above (Apache-2.0 WITH
SHL-2.1, as each file's header says). The
board pin files name the boards' pins (facts of the boards' designs: iCEBreaker by 1BitSquared,
ULX3S by Radiona, Tang Nano 9K by Sipeed). The CMOS inverter uses generic level-1 transistor
models, not a PDK's; the corner templates use the PDKs' own devices and models from the image, and
their CACE testbenches follow CACE's datasheet format.
