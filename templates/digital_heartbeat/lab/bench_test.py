"""A bench test of the Heartbeat test chip with OpenHTF: measures its pulse period and width with a
frequency counter, then sends the test record to this project's Lab in Chipova, with the snapshot
the chips were made from.

    pip install openhtf
    python bench_test.py --url https://chipova.reflex-ddns.com --token chv1.… \\
        --project <project id> --snapshot <snapshot> --dut CHIP-001

Put your counter's driver in FrequencyCounter (PyVISA, say). --simulate stands a pretend counter
in for it, giving the design's own values, to try the way to Chipova: the record says so
(metadata "simulated"), and Chipova shows it as simulated, not as a measurement.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import urllib.request
from pathlib import Path

import openhtf as htf
from openhtf.output.callbacks import json_factory
from openhtf.plugs import BasePlug
from openhtf.util import units


class FrequencyCounter(BasePlug):
    """The instrument on the chip's `out` pin."""

    simulate = False

    def period_us(self) -> float:
        if self.simulate:
            return 2.56
        raise NotImplementedError("read your counter here, e.g. float(inst.query('MEAS:PER?')) * 1e6")

    def width_ns(self) -> float:
        if self.simulate:
            return 10.0
        raise NotImplementedError("read your counter here, e.g. float(inst.query('MEAS:PWID?')) * 1e9")


@htf.measures(
    htf.Measurement("pulse_period_us").in_range(2.50, 2.62).with_units(units.MICROSECOND),
    htf.Measurement("pulse_width_ns").in_range(9, 11).with_units(units.NANOSECOND),
)
@htf.plug(counter=FrequencyCounter)
def heartbeat(test, counter: FrequencyCounter) -> None:
    test.measurements.pulse_period_us = counter.period_us()
    test.measurements.pulse_width_ns = counter.width_ns()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="Chipova's address")
    ap.add_argument("--token", required=True, help="your API token (a project's Agents page)")
    ap.add_argument("--project", required=True)
    ap.add_argument("--snapshot", required=True, help="the snapshot the chips were made from")
    ap.add_argument("--dut", required=True, help="this chip's id (its label)")
    ap.add_argument("--simulate", action="store_true", help="a pretend counter instead of a real one")
    args = ap.parse_args()
    FrequencyCounter.simulate = args.simulate
    out = Path(tempfile.mkdtemp()) / "record.json"
    test = htf.Test(heartbeat, test_name="heartbeat_bench", simulated=args.simulate)
    test.add_output_callbacks(json_factory.OutputToJSON(str(out)))
    test.execute(test_start=lambda: args.dut)
    body = json.dumps({"snapshot": args.snapshot, "record": json.loads(out.read_text())}).encode()
    req = urllib.request.Request(f"{args.url.rstrip('/')}/api/projects/{args.project}/lab", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {args.token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 — your own Chipova
        print("sent to Chipova:", json.loads(r.read())["id"])


if __name__ == "__main__":
    main()
