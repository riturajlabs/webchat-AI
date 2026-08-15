"""RBAC hierarchy tests (Phase 15, backend/core/rbac.py).

The admin API is super_admin-only; tenant management routes accept
owner/admin; `super_admin` satisfies every tenant-level requirement through
the rank hierarchy.
"""

from backend.core.rbac import (
    ROLE_ADMIN,
    ROLE_EDITOR,
    ROLE_OWNER,
    ROLE_SUPER_ADMIN,
    ROLE_USER,
    ROLE_VIEWER,
    has_role,
    meets_any,
    role_rank,
)


def test_rank_ordering() -> None:
    assert role_rank(ROLE_USER) < role_rank(ROLE_EDITOR)
    assert role_rank(ROLE_EDITOR) == role_rank(ROLE_VIEWER)
    assert role_rank(ROLE_EDITOR) < role_rank(ROLE_OWNER)
    assert role_rank(ROLE_OWNER) < role_rank(ROLE_ADMIN)
    assert role_rank(ROLE_ADMIN) < role_rank(ROLE_SUPER_ADMIN)


def test_unknown_role_ranks_below_everything() -> None:
    assert role_rank("typo-role") == 0
    assert has_role("typo-role", ROLE_USER) is False


def test_super_admin_satisfies_all_requirements() -> None:
    for required in (ROLE_USER, ROLE_OWNER, ROLE_ADMIN, ROLE_SUPER_ADMIN):
        assert has_role(ROLE_SUPER_ADMIN, required) is True


def test_only_super_admin_satisfies_super_admin_requirement() -> None:
    for role in (ROLE_USER, ROLE_OWNER, ROLE_ADMIN, ROLE_EDITOR, ROLE_VIEWER):
        assert has_role(role, ROLE_SUPER_ADMIN) is False


def test_owner_meets_owner_but_not_admin() -> None:
    assert has_role(ROLE_OWNER, ROLE_OWNER) is True
    assert has_role(ROLE_OWNER, ROLE_ADMIN) is False


def test_editor_below_owner() -> None:
    assert has_role(ROLE_EDITOR, ROLE_OWNER) is False


def test_meets_any() -> None:
    assert meets_any(ROLE_OWNER, (ROLE_OWNER, ROLE_ADMIN)) is True
    assert meets_any(ROLE_VIEWER, (ROLE_OWNER, ROLE_ADMIN)) is False
    assert meets_any(ROLE_OWNER, ()) is False
