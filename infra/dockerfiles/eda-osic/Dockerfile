# Chipova's full EDA image: IIC-OSIC-TOOLS (OpenROAD, Yosys, KLayout, Magic, Netgen, ngspice,
# Xschem, SiliconCompiler 0.38, the SKY130 / GF180 / IHP SG13G2 PDKs) with SiliconCompiler's
# PDK data baked in, so RTL-to-GDSII runs work with no network.
#
#   docker build -t chipova/eda-osic:2026.10-3 infra/dockerfiles/eda-osic
#
# The base is pinned by digest (about 4 GB to download, 17 GB on disk); these layers add ~250 MB.
FROM hpretl/iic-osic-tools:2026.10@sha256:306585de35d198e70ea58950f77147c86f56c698726a19afea9f1c83009557be

USER root

# SiliconCompiler fetches the lambdapdk data at run time (a 370 MB archive from GitHub); runs
# have no network, so the parts the flows use are cloned in now: a sparse, depth-1 git clone of
# the tag of the installed lambdapdk (v0.2.22), into the cache folder SC computes itself. IHP's
# data root points at the IHP PDK already in the image. sky130 base + sky130hd is all the
# skywater130_demo target reads for plain logic; gf180 base + the 9-track 5 V cells is what
# gf180_demo reads (52 MB). Not baked (add to LAMBDAPDK_PATHS to have them): sky130sram (20 MB),
# sky130io (67 MB), the other gf180 libraries, freepdk45 (9 MB), asap7 (~120 MB).
ARG LAMBDAPDK_PATHS="lambdapdk/sky130/base lambdapdk/sky130/libs/sky130hd lambdapdk/ihp130 lambdapdk/gf180/base lambdapdk/gf180/libs/gf180mcu_fd_sc_mcu9t5v0"

COPY sc_prefetch.py /opt/chipova/sc_prefetch.py

RUN python3 /opt/chipova/sc_prefetch.py --cache /opt/sc-cache --ihp130-local /foss/pdks \
        $LAMBDAPDK_PATHS \
 && chmod -R a+rX,go-w /opt/sc-cache \
 && mkdir -p /etc/siliconcompiler \
 && echo '{"cache": {"cleanupdays": 0}}' > /etc/siliconcompiler/settings.json

# The IHP SG13G2 analog/mixed-signal chip template (JKU; Apache-2.0 WITH SHL-2.1) the Full chip
# flow builds: its 2026.09 release, its generated files removed (make clean-all), without its
# history, tutorial, docs, releases and sizing data, without the flow/artistic submodule (only the
# logo-and-fill step uses it, which needs more memory than a run gets) and without EUROPRACTICE's
# package drawings (not under the template's licence; only the bond plan reads them).
ARG AMS_TEMPLATE_TAG=2026.09
ARG AMS_TEMPLATE_COMMIT=cf12265bd86581579184f281c2d6d59fe32c18a4
RUN set -e; d=/opt/chipova/ams-template; \
    git clone --quiet --depth 1 --branch "$AMS_TEMPLATE_TAG" https://github.com/iic-jku/ihp-sg13g2-ams-chip-template.git "$d"; \
    test "$(git -C "$d" rev-parse HEAD)" = "$AMS_TEMPLATE_COMMIT"; \
    echo "$AMS_TEMPLATE_TAG $AMS_TEMPLATE_COMMIT" > "$d/.chipova-template"; \
    make -s -C "$d" clean-all > /dev/null; \
    rm -rf "$d/.git" "$d/tutorial" "$d/doc" "$d/release" "$d/macros/inverter/scripts/sizing" \
           "$d/packaging/layout/EP_PACKAGES_08022018.gds" "$d/packaging/layout/OP_QFN32_A4_FIT.gds"; \
    chmod -R a+rX,go-w "$d"

# What the image's interactive setup would set, for jobs that start no shell. USER: uid 1000 has
# no passwd entry, and Python's getpass needs a name.
ENV PATH=/foss/tools/bin:/foss/tools/klayout:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LD_LIBRARY_PATH=/foss/tools/klayout:/foss/tools/ngspice/lib \
    PDK_ROOT=/foss/pdks \
    CHIPOVA_SC_CACHE=/opt/sc-cache \
    USER=designer

# Jobs give their own command; the base image's entrypoint would start a desktop.
ENTRYPOINT []
CMD ["bash"]
USER 1000:1000
WORKDIR /work
