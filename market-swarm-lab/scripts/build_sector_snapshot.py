#!/usr/bin/env python3
"""Refresh the sector-constituent snapshot used by the §10/§11 sector gate.

NSE sector-index membership changes ~monthly. This fetches each sector index's constituent
list from niftyindices.com (static CSVs) and writes the snapshot the sector map loads. Run
occasionally (e.g. monthly). niftyindices throttles, so it fetches with delays + retries and
keeps only Fyers-valid index symbols.

    python3 scripts/build_sector_snapshot.py
"""
from __future__ import annotations

import csv
import io
import json
import pathlib
import sys
import time

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

_OUT = pathlib.Path(__file__).resolve().parents[1] / "services" / "nubra_client" / "fixtures" / "sector_constituents.json"
_CSVS = {
    "NSE:NIFTYBANK-INDEX": "ind_niftybanklist.csv", "NSE:NIFTYIT-INDEX": "ind_niftyitlist.csv",
    "NSE:NIFTYPHARMA-INDEX": "ind_niftypharmalist.csv", "NSE:NIFTYAUTO-INDEX": "ind_niftyautolist.csv",
    "NSE:NIFTYMETAL-INDEX": "ind_niftymetallist.csv", "NSE:NIFTYFMCG-INDEX": "ind_niftyfmcglist.csv",
    "NSE:NIFTYENERGY-INDEX": "ind_niftyenergylist.csv", "NSE:NIFTYREALTY-INDEX": "ind_niftyrealtylist.csv",
    "NSE:NIFTYMEDIA-INDEX": "ind_niftymedialist.csv", "NSE:NIFTYPSUBANK-INDEX": "ind_niftypsubanklist.csv",
}


def main() -> None:
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 Chrome/122 Safari/537.36"
    out: dict[str, list[str]] = {}
    for idx, fn in _CSVS.items():
        for _ in range(3):
            try:
                r = s.get(f"https://niftyindices.com/IndexConstituent/{fn}", timeout=20)
                if r.status_code == 200 and r.text.strip():
                    syms = [(row.get("Symbol") or "").strip().upper() for row in csv.DictReader(io.StringIO(r.text))]
                    syms = [x for x in syms if x]
                    if syms:
                        out[idx] = syms
                        print(f"{idx}: {len(syms)}")
                        break
            except requests.RequestException as e:
                print(f"{idx}: retry ({str(e)[:40]})")
            time.sleep(3)
        time.sleep(2)
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print(f"saved {sum(len(v) for v in out.values())} members / {len(out)} indices -> {_OUT}")


if __name__ == "__main__":
    main()
