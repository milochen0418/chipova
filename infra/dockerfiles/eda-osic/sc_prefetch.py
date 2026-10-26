#!/usr/bin/env python3
"""Bake SiliconCompiler data sources into a read-only cache at image build time.

SiliconCompiler 0.38 resolves the lambdapdk data root to a GitHub archive
(https://github.com/siliconcompiler/lambdapdk/archive/refs/tags/v<ver>.tar.gz)
and the ihp130 data root to an IHP-Open-PDK commit archive.  It looks for them
in <cachedir>/dataroot/<name>-<ref16>-<sha1(url+ref)16>/ and accepts any
existing directory there (HTTPResolver.check_cache only tests existence; a
read-only cache dir is used as-is without locking).

This script:
  * asks SC for the exact cache directory names (no guessing of hashes),
  * fetches only the requested lambdapdk sub-trees with a sparse, blob-less,
    depth-1 git clone of the matching tag (a few MB instead of the ~370 MB
    archive), and
  * optionally points the ihp130 data root at the IHP PDK already in the image
    (/foss/pdks contains ihp-sg13g2/, the same layout as the IHP-Open-PDK repo).

usage: sc_prefetch.py --cache /opt/sc-cache [--ihp130-local /foss/pdks] PATH...
       PATH = lambdapdk repo sub-directories, e.g. lambdapdk/sky130/base
"""
import argparse
import os
import shutil
import subprocess
import sys


def resolver(obj, dataroot):
    return obj._find_files_dataroot_resolvers(resolvers=True)[dataroot]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--ihp130-local", default=None)
    ap.add_argument("--repo", default="https://github.com/siliconcompiler/lambdapdk.git")
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args()

    from lambdapdk.sky130 import Sky130PDK
    dataroot = os.path.join(args.cache, "dataroot")
    os.makedirs(dataroot, exist_ok=True)

    r = resolver(Sky130PDK(), "lambdapdk")
    dest = os.path.join(dataroot, r.cache_name)
    print(f"lambdapdk: source={r.source} ref={r.reference} -> {dest}", flush=True)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--branch", r.reference,
                    "--filter=blob:none", "--sparse", args.repo, dest], check=True)
    subprocess.run(["git", "-C", dest, "sparse-checkout", "set", *args.paths], check=True)
    shutil.rmtree(os.path.join(dest, ".git"))

    if args.ihp130_local:
        from lambdapdk.ihp130 import IHP130PDK
        r = resolver(IHP130PDK(), "ihp130")
        link = os.path.join(dataroot, r.cache_name)
        print(f"ihp130: source={r.source} ref={r.reference} -> {link} -> {args.ihp130_local}",
              flush=True)
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(args.ihp130_local, link)

    subprocess.run(["du", "-sh", dataroot], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
