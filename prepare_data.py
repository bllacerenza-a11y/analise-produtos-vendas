"""Download the attributed UCI source and create a small reproducible sample."""

from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parent
SOURCE = "https://archive.ics.uci.edu/static/public/352/online+retail.zip"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, help="Use an already downloaded official ZIP")
    args = parser.parse_args()
    raw_dir = ROOT / "data"
    raw_dir.mkdir(exist_ok=True)
    if args.zip:
        archive = args.zip.read_bytes()
    else:
        with urlopen(Request(SOURCE, headers={"User-Agent": "portfolio-analysis/1.0"}), timeout=90) as response:
            archive = response.read()
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        workbook = zipped.read("Online Retail.xlsx")
    (raw_dir / "Online Retail.xlsx").write_bytes(workbook)
    data = pd.read_excel(io.BytesIO(workbook), dtype={"InvoiceNo": "string", "StockCode": "string"})
    data["InvoiceDate"] = pd.to_datetime(data["InvoiceDate"], errors="coerce")
    data = data.loc[data["InvoiceDate"].ge("2011-01-01") & data["InvoiceDate"].lt("2011-12-01")]
    sample = (data.groupby(data["InvoiceDate"].dt.to_period("M"), group_keys=False)
             .apply(lambda group: group.sample(n=min(700, len(group)), random_state=42),
                    include_groups=False)
             .sort_values("InvoiceDate"))
    sample.to_csv(raw_dir / "online_retail_sample.csv", index=False)
    print(f"Fonte: {len(data):,} linhas no período; amostra documentada: {len(sample):,} linhas")


if __name__ == "__main__":
    main()
