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

from fastapi import APIRouter, Depends
from src.auth.auth_guard import RoleChecker
from src.users.user_model import UserRoleEnum
from src.admin.admin_service import AdminService
from src.admin.dto.admin_response_dto import (
    AdminOverviewStats,
    AdminMediaOverTime,
    AdminWorkspaceStats,
    AdminActiveRole,
    AdminGenerationHealth,
    AdminMonthlyActiveUsers,
    AdminTokenUsageRow,
    AdminTokenUsageRowV2,
    AdminTokenUsageSummary,
    AdminBillingUnitsSummary,
)

router = APIRouter(
    prefix="/api/admin",
    tags=["Admin Dashboard"],
    dependencies=[Depends(RoleChecker(allowed_roles=[UserRoleEnum.ADMIN]))],
)


@router.get("/overview-stats", response_model=AdminOverviewStats)
async def get_overview_stats(
    start_date: str | None = None,
    end_date: str | None = None,
    admin_service: AdminService = Depends(),
):
    """Retrieves platform overview statistics.

    Includes total users, workspaces, and media generated counts.
    """
    return await admin_service.get_overview_stats(
        start_date=start_date, end_date=end_date
    )


@router.get("/media-over-time", response_model=list[AdminMediaOverTime])
async def get_media_over_time(
    start_date: str | None = None,
    end_date: str | None = None,
    admin_service: AdminService = Depends(),
):
    """Retrieves media generation breakdown over time.

    Grouped by date and media type.
    """
    return await admin_service.get_media_over_time(
        start_date=start_date, end_date=end_date
    )


@router.get("/workspace-stats", response_model=list[AdminWorkspaceStats])
async def get_workspace_stats(
    start_date: str | None = None,
    end_date: str | None = None,
    admin_service: AdminService = Depends(),
):
    """Retrieves statistics per workspace.

    Includes total media and breakdown by type for each workspace.
    """
    return await admin_service.get_workspace_stats(
        start_date=start_date, end_date=end_date
    )


@router.get("/active-roles", response_model=list[AdminActiveRole])
async def get_active_roles(
    start_date: str | None = None,
    end_date: str | None = None,
    admin_service: AdminService = Depends(),
):
    """Retrieves distribution of active user roles.

    Counts users assigned to each role.
    """
    return await admin_service.get_active_roles(
        start_date=start_date, end_date=end_date
    )


@router.get("/generation-health", response_model=list[AdminGenerationHealth])
async def get_generation_health(
    start_date: str | None = None,
    end_date: str | None = None,
    admin_service: AdminService = Depends(),
):
    """Retrieves health statistics for media generation jobs.

    Counts jobs by status (completed, failed, processing, stopped).
    """
    return await admin_service.get_generation_health(
        start_date=start_date, end_date=end_date
    )


@router.get(
    "/active-users-monthly", response_model=list[AdminMonthlyActiveUsers]
)
async def get_active_users_monthly(
    start_date: str | None = None,
    end_date: str | None = None,
    admin_service: AdminService = Depends(),
):
    """Retrieves monthly active users evolution.

    Counts distinct users active per month.
    """
    return await admin_service.get_active_users_monthly(
        start_date=start_date, end_date=end_date
    )


@router.post("/cleanup-stuck-jobs")
async def cleanup_stuck_jobs(admin_service: AdminService = Depends()):
    """Cleans up stuck media generation jobs.

    Marks jobs with 'processing' status that are older than 1 hour as 'stopped'.
    """
    count = await admin_service.cleanup_stuck_jobs()
    return {"message": f"Cleaned up {count} stuck jobs", "count": count}


@router.get("/token-usage", response_model=list[AdminTokenUsageRow])
async def get_token_usage(
    days: int = 7,
    admin_service: AdminService = Depends(),
):
    """Retrieves recent token usage rows across all platforms (Creative
    Studio, Genflow, Izumi) from the shared BigQuery usage table. Already
    gated by the router-level RoleChecker(ADMIN) dependency above.
    """
    return await admin_service.get_token_usage(days=days)


@router.get("/token-usage/v2", response_model=list[AdminTokenUsageRowV2])
async def get_token_usage_v2(
    start_date: str,
    end_date: str,
    admin_service: AdminService = Depends(),
):
    """Raw usage rows for a date range, each with its cost in USD."""
    return await admin_service.get_token_usage_v2(start_date=start_date, end_date=end_date)


@router.get("/token-usage/summary", response_model=AdminTokenUsageSummary)
async def get_token_usage_summary(
    start_date: str,
    end_date: str,
    admin_service: AdminService = Depends(),
):
    """Daily / per-model / per-user token usage and cost aggregates."""
    return await admin_service.get_token_usage_summary(start_date=start_date, end_date=end_date)


@router.get("/token-usage/billing-units", response_model=AdminBillingUnitsSummary)
async def get_billing_units_summary(
    start_date: str,
    end_date: str,
    admin_service: AdminService = Depends(),
):
    """Native-unit media costs (Veo/Chirp/Lyria) for a date range --
    separate from token-based usage above.
    """
    return await admin_service.get_billing_units_summary(start_date=start_date, end_date=end_date)
