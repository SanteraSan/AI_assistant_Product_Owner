#!/usr/bin/env python3
"""Issue a long-lived service JWT for n8n → TaskFlow integration calls."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.services.service_jwt import issue_service_jwt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sub", default="n8n-integration")
    parser.add_argument("--tenant-id", default="local_demo")
    parser.add_argument(
        "--roles",
        default="admin,analyst",
        help="Comma-separated roles (default: admin,analyst)",
    )
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=60 * 60 * 24 * 30,
        help="Token TTL (default: 30 days for local n8n demos)",
    )
    args = parser.parse_args()
    settings = get_settings()
    roles = [part.strip() for part in args.roles.split(",") if part.strip()]
    token = issue_service_jwt(
        sub=args.sub,
        tenant_id=args.tenant_id,
        roles=roles,
        secret=settings.service_jwt_secret,
        issuer=settings.service_jwt_issuer,
        audience=settings.service_jwt_audience,
        ttl_seconds=args.ttl_seconds,
        name="n8n Integration",
        email="n8n@taskflow.local",
    )
    print(token)


if __name__ == "__main__":
    main()
