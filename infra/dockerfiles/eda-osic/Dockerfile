# Chipova's full EDA image: IIC-OSIC-TOOLS (OpenROAD, Yosys, KLayout, Magic, Netgen, ngspice,
# Xschem, SiliconCompiler 0.38, the SKY130 / GF180 / IHP SG13G2 PDKs) with SiliconCompiler's
# PDK data baked in, so RTL-to-GDSII runs work with no network.
#
#   docker build -t chipova/eda-osic:2026.10-1 infra/dockerfiles/eda-osic
#
# The base is pinned by digest (about 4 GB to download, 17 GB on disk); this layer adds ~20 MB.
FROM hpretl/iic-osic-tools:2026.10@sha256:306585de35d198e70ea58950f77147c86f56c698726a19afea9f1c83009557be

USER root

# SiliconCompiler fetches the lambdapdk data at run time (a 370 MB archive from GitHub); runs
# have no network, so the parts the flows use are cloned in now: a sparse, depth-1 git clone of
# the tag of the installed lambdapdk (v0.2.22), into the cache folder SC computes itself. IHP's
# data root points at the IHP PDK already in the image. sky130 base + sky130hd is all the
# skywater130_demo target reads for plain logic. Not baked (add to LAMBDAPDK_PATHS to have them):
# sky130sram (20 MB), sky130io (67 MB), freepdk45 (9 MB), gf180 (~54 MB), asap7 (~120 MB).
ARG LAMBDAPDK_PATHS="lambdapdk/sky130/base lambdapdk/sky130/libs/sky130hd lambdapdk/ihp130"

COPY sc_prefetch.py /opt/chipova/sc_prefetch.py

RUN python3 /opt/chipova/sc_prefetch.py --cache /opt/sc-cache --ihp130-local /foss/pdks \
        $LAMBDAPDK_PATHS \
 && chmod -R a+rX,go-w /opt/sc-cache \
 && mkdir -p /etc/siliconcompiler \
 && echo '{"cache": {"cleanupdays": 0}}' > /etc/siliconcompiler/settings.json

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
