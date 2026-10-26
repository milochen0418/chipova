#!/usr/bin/env python3
"""Count violations in a KLayout report database (.lyrdb XML).

usage: lyrdb_count.py report.lyrdb  -> prints JSON {"total": N, "categories": {...}}
Every <item> under <items> is one violation marker; its <category> names the rule.
Categories that exist but have 0 items are reported with 0.
"""
import json
import sys
import xml.etree.ElementTree as ET


def walk_categories(node, prefix=""):
    for cat in node.findall("category"):
        name = prefix + (cat.findtext("name") or "").strip("'")
        yield name
        sub = cat.find("categories")
        if sub is not None:
            yield from walk_categories(sub, name + ".")


def main(path):
    root = ET.parse(path).getroot()
    counts = {}
    cats = root.find("categories")
    if cats is not None:
        for name in walk_categories(cats):
            counts[name] = 0
    items = root.find("items")
    total = 0
    if items is not None:
        for item in items.findall("item"):
            cat = (item.findtext("category") or "").strip().strip("'").replace("'.'", ".")
            counts[cat] = counts.get(cat, 0) + 1
            total += 1
    violated = {k: v for k, v in sorted(counts.items(), key=lambda kv: -kv[1]) if v}
    print(json.dumps({"total": total, "violated": violated,
                      "rules_checked": len(counts)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
