# Chipova's small EDA image: lint, simulation, synthesis, iCE40 FPGA and SPICE.
#
# Debian 13 (trixie) packages, native on amd64 and arm64. Pinned by digest so the same Dockerfile
# builds the same tools; each run still records this image's own digest and the tools' versions.
#
#   docker build -t chipova/eda-base:1 infra/dockerfiles/eda-base
#
# APT_MIRROR points apt at a download cache (re_ddns's pkg-cache: http://pkg-cache:3142/apt);
# the sources are put back afterwards, so the image doesn't depend on it.
FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

ARG APT_MIRROR=
RUN set -eux; \
    src=/etc/apt/sources.list.d/debian.sources; \
    cp "$src" /tmp/debian.sources; \
    if [ -n "$APT_MIRROR" ]; then \
        sed -i "s#http://deb.debian.org#$APT_MIRROR/deb.debian.org#g; s#http://security.debian.org#$APT_MIRROR/security.debian.org#g" "$src"; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        iverilog verilator yosys nextpnr-ice40 fpga-icestorm ngspice graphviz \
        python3 make g++ ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    mv /tmp/debian.sources "$src"; \
    useradd --uid 1000 --create-home --shell /bin/bash eda

USER 1000:1000
WORKDIR /work
