# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from fastapi import Depends
from datetime import datetime, timedelta
from src.admin.repository.admin_repository import AdminRepository
from src.admin.dto.admin_response_dto import (
    AdminTokenUsageRow,
    AdminOverviewStats,
    AdminMediaOverTime,
    AdminWorkspaceStats,
    AdminActiveRole,
    AdminGenerationHealth,
    AdminMonthlyActiveUsers,
    AdminTokenUsageRowV2,
    AdminTokenUsageSummary,
    AdminTokenUsageDailyPoint,
    AdminTokenUsageByModel,
    AdminTokenUsageByUser,
    AdminBillingUnitsSummary,
    AdminBillingUnitRow,
)


class AdminService:
    def __init__(self, admin_repo: AdminRepository = Depends()):
        self.admin_repo = admin_repo

    async def get_overview_stats(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> AdminOverviewStats:
        return await self.admin_repo.get_overview_stats(start_date, end_date)

    async def get_media_over_time(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminMediaOverTime]:
        return await self.admin_repo.get_media_over_time(start_date, end_date)

    async def get_workspace_stats(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminWorkspaceStats]:
        return await self.admin_repo.get_workspace_stats(start_date, end_date)

    async def get_active_roles(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminActiveRole]:
        return await self.admin_repo.get_active_roles(start_date, end_date)

    async def get_generation_health(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminGenerationHealth]:
        return await self.admin_repo.get_generation_health(start_date, end_date)

    async def get_active_users_monthly(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminMonthlyActiveUsers]:
        result_dict = await self.admin_repo.get_active_users_monthly_counts(
            start_date, end_date
        )

        if start_date and end_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(day=1)
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        else:
            end_dt = datetime.today()
            start_dt = (end_dt - timedelta(days=180)).replace(day=1)

        months = []
        curr_dt = start_dt
        while curr_dt <= end_dt:
            months.append(curr_dt.strftime("%Y-%m"))
            if curr_dt.month == 12:
                curr_dt = curr_dt.replace(year=curr_dt.year + 1, month=1)
            else:
                curr_dt = curr_dt.replace(month=curr_dt.month + 1)

        months = sorted(list(set(months)))

        return [
            AdminMonthlyActiveUsers(month=m, count=result_dict.get(m, 0))
            for m in months
        ]

    async def cleanup_stuck_jobs(self) -> int:
        return await self.admin_repo.cleanup_stuck_jobs()


    async def get_token_usage(self, days: int = 7) -> list[AdminTokenUsageRow]:
        """Returns recent token usage rows from BigQuery, newest first.

        TOKEN_USAGE_ADMIN_PAGE_V1: a first, deliberately simple version --
        just the raw rows already logged by log_tokens() (see
        src/common/token_logger.py). Grouping/charts/cost estimates (via
        pricing.json) are left for a later iteration. Uses its own
        BigQuery client directly, since AdminRepository is Postgres-only
        and this is the first admin endpoint to read a different system.
        """
        from google.cloud import bigquery
        client = bigquery.Client(project="ltm-craftstudio-poc")
        query = """
            SELECT timestamp, platform, user_email, model, total
            FROM `ltm-craftstudio-poc.token_usage.usage`
            WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
            ORDER BY timestamp DESC
            LIMIT 500
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days),
            ]
        )
        rows = client.query(query, job_config=job_config).result()
        return [
            AdminTokenUsageRow(
                timestamp=row["timestamp"].isoformat(),
                platform=row["platform"] or "unknown",
                user_email=row["user_email"] or "unknown",
                model=row["model"] or "unknown",
                total=int(row["total"] or 0),
            )
            for row in rows
        ]

    async def get_token_usage_v2(self, start_date: str, end_date: str):
        """TOKEN_USAGE_DASHBOARD_V2: raw rows for a date range, no row
        limit, each with its cost computed via pricing_service.
        """
        from google.cloud import bigquery
        from src.common.pricing_service import load_pricing, cost_usd

        pricing = load_pricing()
        client = bigquery.Client(project="ltm-craftstudio-poc")
        query = """
            SELECT timestamp, platform, user_email, model, tokens_in, tokens_out, total
            FROM `ltm-craftstudio-poc.token_usage.usage`
            WHERE DATE(timestamp) BETWEEN @start_date AND @end_date
            ORDER BY timestamp DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )
        rows = client.query(query, job_config=job_config).result()
        return [
            AdminTokenUsageRowV2(
                timestamp=row["timestamp"].isoformat(),
                platform=row["platform"] or "unknown",
                user_email=row["user_email"] or "unknown",
                model=row["model"] or "unknown",
                tokens_in=int(row["tokens_in"] or 0),
                tokens_out=int(row["tokens_out"] or 0),
                total=int(row["total"] or 0),
                cost_usd=cost_usd(
                    pricing,
                    row["model"] or "unknown",
                    float(row["tokens_in"] or 0),
                    float(row["tokens_out"] or 0),
                ),
            )
            for row in rows
        ]

    async def get_token_usage_summary(self, start_date: str, end_date: str) -> AdminTokenUsageSummary:
        """TOKEN_USAGE_DASHBOARD_V2: daily / per-model / per-user
        aggregates, computed server-side, cost applied per-row before
        aggregation since pricing varies by model.
        """
        from google.cloud import bigquery
        from src.common.pricing_service import load_pricing, cost_usd

        pricing = load_pricing()
        client = bigquery.Client(project="ltm-craftstudio-poc")
        query = """
            SELECT DATE(timestamp) AS day, platform, user_email, model, tokens_in, tokens_out, total
            FROM `ltm-craftstudio-poc.token_usage.usage`
            WHERE DATE(timestamp) BETWEEN @start_date AND @end_date
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )
        rows = list(client.query(query, job_config=job_config).result())

        daily = {}
        by_model = {}
        by_user = {}
        total_tokens = 0
        total_cost = 0.0
        total_calls = 0

        for row in rows:
            model = row["model"] or "unknown"
            user_email = row["user_email"] or "unknown"
            day = row["day"].isoformat()
            tin, tout, total = (
                float(row["tokens_in"] or 0),
                float(row["tokens_out"] or 0),
                int(row["total"] or 0),
            )
            row_cost = cost_usd(pricing, model, tin, tout)

            d = daily.setdefault(day, {"tokens": 0, "cost_usd": 0.0})
            d["tokens"] += total
            d["cost_usd"] += row_cost

            m = by_model.setdefault(model, {"tokens": 0, "cost_usd": 0.0, "calls": 0})
            m["tokens"] += total
            m["cost_usd"] += row_cost
            m["calls"] += 1

            u = by_user.setdefault(user_email, {"tokens": 0, "cost_usd": 0.0, "calls": 0})
            u["tokens"] += total
            u["cost_usd"] += row_cost
            u["calls"] += 1

            total_tokens += total
            total_cost += row_cost
            total_calls += 1

        return AdminTokenUsageSummary(
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            total_calls=total_calls,
            daily=[
                AdminTokenUsageDailyPoint(date=k, tokens=v["tokens"], cost_usd=v["cost_usd"])
                for k, v in sorted(daily.items())
            ],
            by_model=[
                AdminTokenUsageByModel(model=k, tokens=v["tokens"], cost_usd=v["cost_usd"], calls=v["calls"])
                for k, v in sorted(by_model.items(), key=lambda kv: -kv[1]["cost_usd"])
            ],
            by_user=[
                AdminTokenUsageByUser(user_email=k, tokens=v["tokens"], cost_usd=v["cost_usd"], calls=v["calls"])
                for k, v in sorted(by_user.items(), key=lambda kv: -kv[1]["cost_usd"])
            ],
        )

    async def get_billing_units_summary(self, start_date: str, end_date: str) -> AdminBillingUnitsSummary:
        """TOKEN_USAGE_DASHBOARD_V2: native-unit media costs (Veo seconds,
        Chirp characters, Lyria generations) for the same date range --
        shown as a clearly separate section from token-based usage.
        """
        from google.cloud import bigquery
        from src.common.pricing_service import load_pricing, cost_units_usd

        pricing = load_pricing()
        client = bigquery.Client(project="ltm-craftstudio-poc")
        query = """
            SELECT platform, model, unit_type, SUM(quantity) AS qty, COUNT(*) AS calls
            FROM `ltm-craftstudio-poc.token_usage.billing_units`
            WHERE DATE(timestamp) BETWEEN @start_date AND @end_date
            GROUP BY platform, model, unit_type
            ORDER BY platform, model
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )
        rows = list(client.query(query, job_config=job_config).result())

        result_rows = []
        total_cost = 0.0
        for row in rows:
            qty = float(row["qty"] or 0)
            row_cost = cost_units_usd(pricing, row["model"], row["unit_type"], qty)
            total_cost += row_cost
            result_rows.append(
                AdminBillingUnitRow(
                    platform=row["platform"] or "unknown",
                    model=row["model"] or "unknown",
                    unit_type=row["unit_type"] or "unknown",
                    quantity=qty,
                    cost_usd=row_cost,
                    calls=int(row["calls"] or 0),
                )
            )

        return AdminBillingUnitsSummary(total_cost_usd=total_cost, rows=result_rows)
