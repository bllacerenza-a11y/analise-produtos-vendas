"""Reproducible analysis of the UCI Online Retail transactions."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent
REQUIRED = {"InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice", "Country"}


def load_sales(path: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    if path.suffix.lower() == ".xlsx":
        raw = pd.read_excel(path, dtype={"InvoiceNo": "string", "StockCode": "string"})
    else:
        raw = pd.read_csv(path, dtype={"InvoiceNo": "string", "StockCode": "string"})
    missing = REQUIRED.difference(raw.columns)
    if missing:
        raise ValueError(f"Colunas ausentes: {', '.join(sorted(missing))}")

    raw["InvoiceDate"] = pd.to_datetime(raw["InvoiceDate"], errors="coerce")
    raw["Quantity"] = pd.to_numeric(raw["Quantity"], errors="coerce")
    raw["UnitPrice"] = pd.to_numeric(raw["UnitPrice"], errors="coerce")
    invoice = raw["InvoiceNo"].fillna("").str.upper()
    cancelled = invoice.str.startswith("C") | raw["Quantity"].le(0)
    bad = (
        raw["InvoiceDate"].isna()
        | raw["StockCode"].isna()
        | raw["Description"].isna()
        | raw["Quantity"].isna()
        | raw["UnitPrice"].isna()
        | raw["UnitPrice"].le(0)
        | invoice.eq("")
    )
    in_period = raw["InvoiceDate"].ge("2011-01-01") & raw["InvoiceDate"].lt("2011-12-01")
    clean = raw.loc[in_period & ~cancelled & ~bad, list(REQUIRED)].copy()
    clean["RevenueGBP"] = clean["Quantity"] * clean["UnitPrice"]
    clean["Month"] = clean["InvoiceDate"].dt.strftime("%Y-%m")
    quality = {
        "source_rows": int(len(raw)),
        "cancelled_or_nonpositive_quantity_rows": int(cancelled.sum()),
        "invalid_rows": int(bad.sum()),
        "excluded_outside_jan_nov_2011": int((~in_period).sum()),
        "analyzed_rows": int(len(clean)),
    }
    return clean, quality


def aggregate(clean: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    with sqlite3.connect(":memory:") as conn:
        clean.to_sql("sales_lines", conn, index=False)
        monthly = pd.read_sql_query(
            "SELECT Month AS month, ROUND(SUM(RevenueGBP), 2) AS revenue_gbp, "
            "COUNT(DISTINCT InvoiceNo) AS orders FROM sales_lines GROUP BY Month ORDER BY Month", conn
        )
        products = pd.read_sql_query(
            "SELECT StockCode AS stock_code, MIN(Description) AS description, "
            "ROUND(SUM(RevenueGBP), 2) AS revenue_gbp, SUM(Quantity) AS units "
            "FROM sales_lines WHERE StockCode GLOB '*[0-9]*' "
            "GROUP BY StockCode ORDER BY revenue_gbp DESC LIMIT 10", conn
        )
        countries = pd.read_sql_query(
            "SELECT Country AS country, ROUND(SUM(RevenueGBP), 2) AS revenue_gbp "
            "FROM sales_lines WHERE Country <> 'United Kingdom' GROUP BY Country "
            "ORDER BY revenue_gbp DESC LIMIT 8", conn
        )
    order_totals = clean.groupby("InvoiceNo")["RevenueGBP"].sum()
    metrics = {
        "period": "2011-01 a 2011-11 (dezembro de 2011 é parcial na fonte)",
        "gross_sales_gbp": round(float(clean["RevenueGBP"].sum()), 2),
        "orders": int(clean["InvoiceNo"].nunique()),
        "units": int(clean["Quantity"].sum()),
        "median_order_gbp": round(float(order_totals.median()), 2),
        "products": int(clean["StockCode"].nunique()),
    }
    return monthly, products, countries, metrics


def render_dashboard(monthly: pd.DataFrame, products: pd.DataFrame, countries: pd.DataFrame,
                     metrics: dict, quality: dict, target: Path) -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig = plt.figure(figsize=(15, 9), facecolor="#f3f7fb")
    grid = fig.add_gridspec(3, 2, height_ratios=[0.9, 2.2, 2.2], hspace=0.68, wspace=0.27)
    fig.text(0.055, 0.955, "PRODUTOS & VENDAS", fontsize=22, weight="bold", color="#102a43")
    fig.text(0.055, 0.925, "Online Retail · Reino Unido · janeiro–novembro de 2011 · valores em GBP",
             fontsize=10, color="#526b80")
    kpis = [
        ("Vendas brutas válidas", f"£{metrics['gross_sales_gbp']:,.0f}".replace(",", ".")),
        ("Pedidos", f"{metrics['orders']:,}".replace(",", ".")),
        ("Ticket mediano", f"£{metrics['median_order_gbp']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")),
        ("Linhas analisadas", f"{quality['analyzed_rows']:,}".replace(",", ".")),
    ]
    axk = fig.add_subplot(grid[0, :]); axk.axis("off")
    for i, (label, value) in enumerate(kpis):
        x = 0.02 + i * 0.25
        axk.text(x, 0.77, label, transform=axk.transAxes, color="#526b80", fontsize=10)
        axk.text(x, 0.23, value, transform=axk.transAxes, color="#102a43", fontsize=19, weight="bold")
    axes = [fig.add_subplot(grid[1, 0]), fig.add_subplot(grid[1, 1]),
            fig.add_subplot(grid[2, 0]), fig.add_subplot(grid[2, 1])]
    for ax in axes:
        ax.set_facecolor("white")
        for spine in ax.spines.values(): spine.set_visible(False)
        ax.grid(axis="y", color="#e5edf4", zorder=0)
    axes[0].plot(monthly["month"], monthly["revenue_gbp"] / 1e6, color="#087e8b", lw=2.8, marker="o")
    axes[0].set_title("Vendas mensais", loc="left", weight="bold", color="#102a43")
    axes[0].set_ylabel("Milhões de GBP")
    axes[0].tick_params(axis="x", rotation=40)
    top = products.head(7).iloc[::-1]
    axes[1].barh(top["stock_code"], top["revenue_gbp"] / 1000, color="#3d85c6", zorder=2)
    axes[1].set_title("Produtos com maior faturamento", loc="left", weight="bold", color="#102a43")
    axes[1].set_xlabel("Milhares de GBP")
    topc = countries.head(7).iloc[::-1]
    axes[2].barh(topc["country"], topc["revenue_gbp"] / 1000, color="#48a9a6", zorder=2)
    axes[2].set_title("Mercados fora do Reino Unido", loc="left", weight="bold", color="#102a43")
    axes[2].set_xlabel("Milhares de GBP")
    axes[3].axis("off")
    notes = [
        "CRITÉRIOS DA ANÁLISE",
        "• Transações de janeiro a novembro de 2011",
        "• Cancelamentos e quantidades não positivas excluídos",
        "• Preço não positivo e campos essenciais ausentes excluídos",
        "• CustomerID ausente não elimina venda válida",
        "• Vendas brutas válidas; não representam lucro",
        "",
        f"Linhas canceladas/quantidade ≤ 0: {quality['cancelled_or_nonpositive_quantity_rows']:,}".replace(",", "."),
        f"Linhas inválidas: {quality['invalid_rows']:,}".replace(",", "."),
    ]
    for j, line in enumerate(notes):
        axes[3].text(0.02, 0.91 - j * 0.095, line, transform=axes[3].transAxes,
                     fontsize=10 if j else 13, weight="bold" if j == 0 else "normal", color="#102a43")
    fig.text(0.055, 0.025, "Fonte: Chen (2015), UCI Online Retail, CC BY 4.0 · doi:10.24432/C5BW33",
             fontsize=9, color="#526b80")
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "online_retail_sample.csv")
    parser.add_argument("--out", type=Path, default=ROOT / "report")
    args = parser.parse_args()
    clean, quality = load_sales(args.input)
    if clean.empty:
        raise ValueError("Nenhuma linha válida no período de janeiro a novembro de 2011")
    monthly, products, countries, metrics = aggregate(clean)
    args.out.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(args.out / "monthly_sales.csv", index=False)
    products.to_csv(args.out / "top_products.csv", index=False)
    countries.to_csv(args.out / "top_countries_ex_uk.csv", index=False)
    (args.out / "metrics.json").write_text(json.dumps({"metrics": metrics, "quality": quality},
                                                ensure_ascii=False, indent=2), encoding="utf-8")
    render_dashboard(monthly, products, countries, metrics, quality, args.out / "dashboard.png")
    print(json.dumps({"metrics": metrics, "quality": quality}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
