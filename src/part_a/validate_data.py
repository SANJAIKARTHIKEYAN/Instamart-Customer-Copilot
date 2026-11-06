"""Standalone Part A checkpoint validator."""
from pathlib import Path
import pandas as pd
from src.part_a.pipeline import CLEAN, DB_PATH, build_database, validate

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    customers = pd.read_csv(CLEAN / "customers.csv", parse_dates=["signup_date"])
    products = pd.read_csv(CLEAN / "products.csv")
    orders = pd.read_csv(CLEAN / "orders.csv", parse_dates=["order_ts"])
    validate(customers, products, orders)


if __name__ == "__main__":
    main()
