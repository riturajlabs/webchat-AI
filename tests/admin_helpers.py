"""Shared helpers for building a fake-backed admin API test environment.

The admin layer shares the same underlying fakes as the auth service so that
accounts registered through `/api/auth/register` are visible to the admin
endpoints and admin mutations (suspend/force-logout) are observable on the
same objects. `FakeAdminRepository` aggregates the tenant/user/usage/crawl
fakes exactly like `MongoAdminRepository` aggregates the real collections.
"""

from dataclasses import dataclass

from backend.services.admin import AdminService

from tests.auth_helpers import AuthEnv, build_auth_env
from tests.fakes import (
    FakeAdminRepository,
    FakeCrawlJobRepository,
    FakeTenantRepository,
    FakeUsageRecordRepository,
    FakeUserRepository,
    FakeWebsiteRepository,
)


@dataclass
class AdminEnv:
    users: FakeUserRepository
    tenants: FakeTenantRepository
    websites: FakeWebsiteRepository
    usage: FakeUsageRecordRepository
    crawl_jobs: FakeCrawlJobRepository
    auth: AuthEnv
    admin: AdminService


def build_admin_env() -> AdminEnv:
    auth = build_auth_env()
    websites = FakeWebsiteRepository()
    usage = FakeUsageRecordRepository()
    crawl_jobs = FakeCrawlJobRepository()
    stats = FakeAdminRepository(
        tenants=auth.tenants,
        users=auth.users,
        usage=usage,
        crawl_jobs=crawl_jobs,
    )
    admin = AdminService(
        tenants=auth.tenants,
        users=auth.users,
        websites=websites,
        usage=usage,
        crawl_jobs=crawl_jobs,
        audit=auth.audit,
        refresh_tokens=auth.refresh_tokens,
        stats=stats,
    )
    return AdminEnv(
        users=auth.users,
        tenants=auth.tenants,
        websites=websites,
        usage=usage,
        crawl_jobs=crawl_jobs,
        auth=auth,
        admin=admin,
    )
