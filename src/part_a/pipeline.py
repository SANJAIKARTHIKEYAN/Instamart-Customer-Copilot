"""Part A: audit, clean, persist, and validate the synthetic Instamart data."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
OUTPUTS = ROOT / "outputs"
DB_PATH = ROOT / "data" / "instamart.db"


def audit_frame(df: pd.DataFrame) -> dict:
    missing = df.isna().sum()
    return {
        "shape": [int(df.shape[0]), int(df.shape[1])],
        "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
        "missing": {
            str(col): {
                "count": int(missing[col]),
                "percentage": round(float(missing[col]) / len(df) * 100, 2) if len(df) else 0.0,
            }
            for col in df.columns
        },
    }


def audit_raw_data() -> dict:
    customers = pd.read_csv(RAW / "customers.csv")
    products = pd.read_csv(RAW / "products.csv")
    orders = pd.read_csv(RAW / "orders.csv")
    # Keep empty ticket strings as empty strings; this is important for Part C.
    tickets = pd.read_csv(RAW / "tickets.csv", keep_default_na=False)

    numeric_amount = pd.to_numeric(orders["order_amount"], errors="coerce")
    delivery_numeric = pd.to_numeric(orders["delivery_minutes"], errors="coerce")
    age_numeric = pd.to_numeric(customers["age"].replace("", np.nan), errors="coerce")
    gender_nonblank = customers.loc[customers["gender"].notna() & customers["gender"].astype(str).str.strip().ne(""), "gender"]

    report = {
        "tables": {
            "customers": audit_frame(customers),
            "products": audit_frame(products),
            "orders": audit_frame(orders),
            "tickets": audit_frame(tickets),
        },
        "reference_audit": {
            "raw_orders_rows": int(len(orders)),
            "exact_duplicate_rows": int(orders.duplicated().sum()),
            "pending_rows": int(orders["status"].eq("pending").sum()),
            "distinct_order_ids": int(orders["order_id"].nunique()),
            "non_numeric_order_amounts": int(numeric_amount.isna().sum()),
            "negative_delivery_minutes": int((delivery_numeric < 0).sum()),
            "blank_delivery_minutes": int(orders["delivery_minutes"].isna().sum() + orders["delivery_minutes"].astype(str).str.strip().eq("").sum()),
            "blank_customer_ages": int(customers["age"].isna().sum() + customers["age"].astype(str).str.strip().eq("").sum()),
            "ages_outside_10_100": int(((age_numeric < 10) | (age_numeric > 100)).sum()),
            "distinct_raw_city_spellings": int(customers["city"].nunique()),
            "distinct_nonblank_raw_gender_spellings": int(gender_nonblank.nunique()),
            "blank_customer_genders": int(customers["gender"].isna().sum() + customers["gender"].astype(str).str.strip().eq("").sum()),
        },
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    (OUTPUTS / "raw_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("RAW DATA AUDIT")
    print(json.dumps(report["reference_audit"], indent=2))
    return report


def clean_customers(customers_raw: pd.DataFrame) -> pd.DataFrame:
    customers = customers_raw.copy()
    customers["city"] = customers["city"].astype(str).str.strip().str.title()
    gender_map = {
        "male": "male", "m": "male",
        "female": "female", "f": "female",
    }
    customers["gender"] = (
        customers["gender"].astype(str).str.strip().str.lower().map(gender_map).fillna("unknown")
    )
    customers["age"] = pd.to_numeric(customers["age"].replace("", np.nan), errors="coerce")
    customers.loc[~customers["age"].between(10, 100), "age"] = np.nan
    customers["age"] = customers["age"].fillna(
        customers.groupby("city")["age"].transform("median")
    )
    # A final integer conversion is safe because source ages and city medians are integers.
    customers["age"] = customers["age"].round().astype(int)
    customers["signup_date"] = pd.to_datetime(customers["signup_date"], errors="raise")
    return customers


def clean_orders(orders_raw: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    orders = orders_raw.copy()
    orders["order_ts"] = pd.to_datetime(orders["order_ts"], errors="raise")
    # The required order is exact-row deduplication, then latest record per order_id.
    orders = orders.drop_duplicates().copy()
    orders = orders.sort_values(["order_id", "order_ts"], kind="stable")
    orders = orders.drop_duplicates(subset=["order_id"], keep="last").copy()

    for col in ["quantity", "discount_pct", "delivery_minutes"]:
        orders[col] = pd.to_numeric(orders[col].replace("", np.nan), errors="coerce")
    orders["order_amount"] = pd.to_numeric(orders["order_amount"], errors="coerce")
    orders = orders.merge(products[["product_id", "price_inr", "category"]], on="product_id", how="left", validate="many_to_one")
    amount_missing = orders["order_amount"].isna()
    orders.loc[amount_missing, "order_amount"] = (
        orders.loc[amount_missing, "price_inr"]
        * orders.loc[amount_missing, "quantity"]
        * (1 - orders.loc[amount_missing, "discount_pct"] / 100)
    ).round(2)

    orders.loc[orders["delivery_minutes"] < 0, "delivery_minutes"] = np.nan
    completed = orders["status"].eq("completed")
    category_medians = orders.loc[completed].groupby("category")["delivery_minutes"].transform("median")
    # Assign medians by the matching row indices, without imputing cancelled orders.
    completed_rows = orders.loc[completed].copy()
    completed_rows["category_median"] = completed_rows.groupby("category")["delivery_minutes"].transform("median")
    missing_completed = completed & orders["delivery_minutes"].isna()
    median_by_index = completed_rows["category_median"]
    orders.loc[missing_completed, "delivery_minutes"] = median_by_index.reindex(orders.index[missing_completed]).to_numpy()

    orders = orders.drop(columns=["price_inr", "category"])
    orders["quantity"] = orders["quantity"].astype(int)
    orders["discount_pct"] = orders["discount_pct"].astype(int)
    orders["order_amount"] = orders["order_amount"].round(2)
    orders["delivery_minutes"] = orders["delivery_minutes"].round().astype("Int64")
    return orders.sort_values("order_id", kind="stable").reset_index(drop=True)


def build_database(customers: pd.DataFrame, products: pd.DataFrame, orders: pd.DataFrame) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    db_customers = customers.copy()
    db_customers["signup_date"] = db_customers["signup_date"].dt.strftime("%Y-%m-%d")
    db_orders = orders.copy()
    db_orders["order_ts"] = db_orders["order_ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        db_customers.to_sql("customers", conn, index=False, if_exists="replace")
        products.to_sql("products", conn, index=False, if_exists="replace")
        db_orders.to_sql("orders", conn, index=False, if_exists="replace")


def validate(customers: pd.DataFrame, products: pd.DataFrame, orders: pd.DataFrame) -> None:
    assert len(customers) == 1200, f"customers rows: {len(customers)}"
    assert len(products) == 40, f"products rows: {len(products)}"
    assert len(orders) == 12309, f"orders rows: {len(orders)}"
    assert orders["order_id"].nunique() == 12309
    assert orders["status"].value_counts().to_dict() == {"completed": 11110, "cancelled": 1199}
    assert orders["order_amount"].notna().all()
    assert orders.loc[orders["status"].eq("completed"), "delivery_minutes"].notna().all()
    assert orders.loc[orders["status"].eq("cancelled"), "delivery_minutes"].isna().all()
    revenue = round(float(orders.loc[orders["status"].eq("completed"), "order_amount"].sum()), 2)
    assert revenue == 2998668.80, f"completed revenue: {revenue}"
    assert customers["age"].notna().all()
    assert customers["age"].between(18, 60).all()
    assert set(customers["city"].unique()) == {"Pune", "Delhi", "Bengaluru", "Chennai", "Hyderabad", "Mumbai"}
    assert set(customers["gender"].unique()) <= {"female", "male", "unknown"}
    with sqlite3.connect(DB_PATH) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"customers", "products", "orders"} <= tables
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 12309
    print("ALL CHECKPOINTS PASSED")


def run() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    CLEAN.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    audit_raw_data()

    customers_raw = pd.read_csv(RAW / "customers.csv")
    products = pd.read_csv(RAW / "products.csv")
    orders_raw = pd.read_csv(RAW / "orders.csv")
    customers = clean_customers(customers_raw)
    orders = clean_orders(orders_raw, products)

    customers.to_csv(CLEAN / "customers.csv", index=False, date_format="%Y-%m-%d")
    products.to_csv(CLEAN / "products.csv", index=False)
    orders.to_csv(CLEAN / "orders.csv", index=False, date_format="%Y-%m-%d %H:%M:%S")
    build_database(customers, products, orders)
    validate(customers, products, orders)

    print("\nCLEANING CHECKPOINTS")
    print("Customer cities:", customers["city"].value_counts().to_dict())
    print("Customer genders:", customers["gender"].value_counts().to_dict())
    print("Orders by status:", orders["status"].value_counts().to_dict())
    print("Completed revenue INR:", f"{orders.loc[orders['status'].eq('completed'), 'order_amount'].sum():.2f}")


if __name__ == "__main__":
    run()
