"""Execute the seven required SQL queries and pandas cross-checks."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "instamart.db"
SQL_FILE = ROOT / "sql" / "queries.sql"
OUT = ROOT / "outputs" / "part_a_analysis.json"


def split_queries(text: str) -> list[str]:
    # The supplied SQL file uses semicolons only to terminate complete statements.
    return [chunk.strip() for chunk in text.split(";") if chunk.strip()]


def main() -> None:
    queries = split_queries(SQL_FILE.read_text(encoding="utf-8"))
    with sqlite3.connect(DB) as conn:
        results = [pd.read_sql_query(query, conn) for query in queries]
        avg_spend = pd.read_sql_query(
            """WITH customer_spend AS (
                   SELECT customer_id, SUM(order_amount) AS total_spend
                   FROM orders WHERE status='completed' GROUP BY customer_id
               ) SELECT AVG(total_spend) AS average_customer_spend FROM customer_spend""",
            conn,
        ).iloc[0, 0]
        completed = pd.read_sql_query(
            """SELECT o.*, c.city, p.category FROM orders o
               JOIN customers c ON c.customer_id=o.customer_id
               JOIN products p ON p.product_id=o.product_id
               WHERE o.status='completed'""", conn
        )

    q2 = results[1]
    pivot = pd.pivot_table(
        completed, values="order_amount", index="city", columns="category",
        aggfunc="sum", fill_value=0, margins=True, margins_name="All"
    )
    city_agg = completed.groupby("city").agg(
        sum_inr=("order_amount", "sum"),
        mean_inr=("order_amount", "mean"),
        count=("order_amount", "count"),
    ).round({"sum_inr": 2, "mean_inr": 2})
    amount = completed["order_amount"]
    q1, q3 = amount.quantile([0.25, 0.75])
    iqr = q3 - q1
    correlations = completed[["order_amount", "discount_pct", "quantity", "delivery_minutes"]].corr()
    corr_pairs = []
    cols = list(correlations.columns)
    for i, left in enumerate(cols):
        for right in cols[i + 1:]:
            corr_pairs.append((left, right, float(correlations.loc[left, right])))
    largest_corr = max(corr_pairs, key=lambda x: abs(x[2]))

    report = {
        "sql": {
            "q1_customers": len(results[0]),
            "q2_rows": len(q2),
            "q2_total_revenue_inr": round(float(q2["revenue_inr"].sum()), 2),
            "q2_largest_cell": q2.sort_values("revenue_inr").iloc[-1].to_dict(),
            "q3_products": len(results[2]),
            "q4_customers_without_completed_orders": len(results[3]),
            "q5_customers_above_average": len(results[4]),
            "q5_average_customer_spend_inr": round(float(avg_spend), 2),
            "q6_top_customer_by_city": results[5].sort_values(["city", "spend_rank", "customer_id"]).groupby("city", as_index=False).first()[["city", "customer_id", "total_spend"]].to_dict("records"),
            "q6_rank_vs_row_number_differences": int((results[5]["spend_rank"] != results[5]["spend_row_number"]).sum()),
            "q7_daily_rows": len(results[6]),
            "q7_last_cumulative_revenue_inr": round(float(results[6].iloc[-1]["cumulative_revenue_inr"]), 2),
        },
        "pandas": {
            "pivot_grand_total_inr": round(float(pivot.loc["All", "All"]), 2),
            "city_aggregates": [{"city": city, **row} for city, row in city_agg.to_dict("index").items()],
            "amount_mean_inr": round(float(amount.mean()), 2),
            "amount_median_inr": round(float(amount.median()), 2),
            "amount_skewness": round(float(amount.skew()), 2),
            "q1_inr": round(float(q1), 2),
            "q2_median_inr": round(float(amount.quantile(0.5)), 2),
            "q3_inr": round(float(q3), 2),
            "lower_fence_inr": round(float(q1 - 1.5 * iqr), 2),
            "upper_fence_inr": round(float(q3 + 1.5 * iqr), 2),
            "outliers_below_lower_fence": int((amount < q1 - 1.5 * iqr).sum()),
            "outliers_above_upper_fence": int((amount > q3 + 1.5 * iqr).sum()),
            "largest_absolute_correlation": {"left": largest_corr[0], "right": largest_corr[1], "value": round(largest_corr[2], 3)},
            "correlation_matrix": correlations.round(3).to_dict(),
        },
    }
    OUT.write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    print(json.dumps(report, indent=2, default=float))
    print(f"Saved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
