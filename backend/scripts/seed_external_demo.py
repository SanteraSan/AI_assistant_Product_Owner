#!/usr/bin/env python3
"""Seed synthetic external demo DB (port 5433) for E4 sync."""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DEFAULT_DSN = (
    "postgresql+asyncpg://external_user:external_password@localhost:5433/external_demo"
)


async def main() -> None:
    dsn = os.environ.get("EXTERNAL_POSTGRES_DSN", DEFAULT_DSN)
    engine = create_async_engine(dsn, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS demo_customers (
                    external_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    segment TEXT NOT NULL,
                    arr_usd INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS demo_support_tickets (
                    external_id TEXT PRIMARY KEY,
                    customer_external_id TEXT NOT NULL REFERENCES demo_customers(external_id),
                    subject TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    product_area TEXT NOT NULL
                )
                """
            )
        )
        await conn.execute(text("DELETE FROM demo_support_tickets"))
        await conn.execute(text("DELETE FROM demo_customers"))
        await conn.execute(
            text(
                """
                INSERT INTO demo_customers (external_id, name, segment, arr_usd) VALUES
                ('cust_northwind', 'Northwind Logistics', 'enterprise', 240000),
                ('cust_aurora', 'Aurora Retail Group', 'enterprise', 180000),
                ('cust_pebble', 'Pebble Labs', 'midmarket', 42000)
                """
            )
        )
        await conn.execute(
            text(
                """
                INSERT INTO demo_support_tickets (
                    external_id, customer_external_id, subject, status, priority, product_area
                ) VALUES
                (
                    'tkt_1001',
                    'cust_northwind',
                    'Slack notifications delayed 20 minutes after status change',
                    'open',
                    'high',
                    'notifications'
                ),
                (
                    'tkt_1002',
                    'cust_aurora',
                    'Webhook retries flood Slack during peak hours',
                    'open',
                    'high',
                    'notifications'
                ),
                (
                    'tkt_1003',
                    'cust_pebble',
                    'CSV import fails on UTF-8 BOM headers',
                    'open',
                    'medium',
                    'csv_import'
                ),
                (
                    'tkt_1004',
                    'cust_northwind',
                    'Need digest mode for night-time Slack alerts',
                    'open',
                    'medium',
                    'notifications'
                )
                """
            )
        )
    await engine.dispose()
    print("Seeded external_demo: demo_customers=3, demo_support_tickets=4")


if __name__ == "__main__":
    asyncio.run(main())
