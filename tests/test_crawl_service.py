"""Unit tests for the crawl orchestration service (Phase 4)."""

import pytest
from backend.core.errors import (
    CrawlConflictError,
    CrawlJobNotFoundError,
    WebsiteNotFoundError,
)
from backend.models.audit_log import AUDIT_CRAWL_STARTED
from backend.models.crawl_job import (
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_PENDING,
    CRAWL_STATUS_RUNNING,
    CrawlJob,
)
from backend.models.website import WEBSITE_STATUS_CRAWLING, Website
from backend.services.auth import Principal
from tests.crawl_helpers import build_crawl_env
from tests.website_helpers import make_principal


@pytest.fixture
def env():
    return build_crawl_env()


async def _add_website(
    env, *, tenant_id: str = "tenant-a", url: str = "https://acme.example/"
) -> Website:
    website = Website.new(tenant_id=tenant_id, name="Acme", url=url)
    await env.websites.create(website)
    return website


async def test_start_crawl_creates_pending_job_and_enqueues(env) -> None:
    website = await _add_website(env)
    principal: Principal = make_principal(tenant_id="tenant-a")

    job = await env.service.start_crawl(
        principal=principal, website_id=website.id, ip_address="1.2.3.4", user_agent="test"
    )

    assert job.status == CRAWL_STATUS_PENDING
    assert job.website_id == website.id
    assert job.tenant_id == "tenant-a"
    assert env.enqueued == [job.id]
    assert env.websites.websites[website.id].status == WEBSITE_STATUS_CRAWLING
    assert any(log.action == AUDIT_CRAWL_STARTED for log in env.audit.logs)
    assert job.id in env.crawl_jobs.jobs


async def test_start_crawl_missing_website_raises(env) -> None:
    principal: Principal = make_principal(tenant_id="tenant-a")
    with pytest.raises(WebsiteNotFoundError):
        await env.service.start_crawl(
            principal=principal, website_id="missing", ip_address=None, user_agent=None
        )
    assert env.enqueued == []


async def test_start_crawl_rejects_active_job(env) -> None:
    website = await _add_website(env)
    active = CrawlJob.new(tenant_id="tenant-a", website_id=website.id)
    active.status = CRAWL_STATUS_RUNNING
    await env.crawl_jobs.create(active)
    principal: Principal = make_principal(tenant_id="tenant-a")

    with pytest.raises(CrawlConflictError):
        await env.service.start_crawl(
            principal=principal, website_id=website.id, ip_address=None, user_agent=None
        )
    assert env.enqueued == []


async def test_start_crawl_allows_new_job_after_completion(env) -> None:
    website = await _add_website(env)
    done = CrawlJob.new(tenant_id="tenant-a", website_id=website.id)
    done.status = CRAWL_STATUS_COMPLETED
    await env.crawl_jobs.create(done)
    principal: Principal = make_principal(tenant_id="tenant-a")

    job = await env.service.start_crawl(
        principal=principal, website_id=website.id, ip_address=None, user_agent=None
    )
    assert job.status == CRAWL_STATUS_PENDING
    assert env.enqueued == [job.id]


async def test_get_crawl_job_returns_owned_job(env) -> None:
    job = CrawlJob.new(tenant_id="tenant-a", website_id="website-a")
    await env.crawl_jobs.create(job)

    found = await env.service.get_crawl_job("tenant-a", job.id)
    assert found.id == job.id


async def test_get_crawl_job_missing_raises(env) -> None:
    with pytest.raises(CrawlJobNotFoundError):
        await env.service.get_crawl_job("tenant-a", "missing")


async def test_crawl_job_tenant_isolation(env) -> None:
    job = CrawlJob.new(tenant_id="tenant-a", website_id="website-a")
    await env.crawl_jobs.create(job)

    with pytest.raises(CrawlJobNotFoundError):
        await env.service.get_crawl_job("tenant-b", job.id)
