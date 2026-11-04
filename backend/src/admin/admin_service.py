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
