"""Role-based access control (Phase 15, SaaS admin operations).

The platform recognizes four canonical roles:

    user           base account role (no management rights)
    owner          a workspace's founding/primary member (tenant-level)
    admin          tenant administrator (tenant-level, above owner)
    super_admin    platform operator (cross-tenant, the only role that may
                   call the `/api/admin/*` surface)

The legacy tenant membership roles `editor`/`viewer` rank below `owner` and
are preserved so existing memberships keep working.

RBAC is enforced with a numeric hierarchy (`role_rank`): a principal whose
rank is *at least* the required rank passes the check, so `super_admin`
satisfies every tenant-level requirement while remaining the only role that
passes a `super_admin` requirement. Tenant isolation itself is enforced by
`AuthService.authenticate` (which re-checks the live tenant) - this module
only decides *which role* may call which route.
"""

ROLE_USER = "user"
ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"

# Legacy tenant membership roles below owner (kept for existing memberships).
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"

ROLE_RANKS: dict[str, int] = {
    ROLE_USER: 10,
    ROLE_EDITOR: 20,
    ROLE_VIEWER: 20,
    ROLE_OWNER: 30,
    ROLE_ADMIN: 40,
    ROLE_SUPER_ADMIN: 100,
}

# The only roles allowed on the `/api/admin/*` router (Phase 15).
ADMIN_ROLES = frozenset({ROLE_SUPER_ADMIN})


def role_rank(role: str) -> int:
    """Return the numeric rank for a role (0 for unknown roles).

    Unknown roles rank below everything so a typo fails closed rather than
    granting access.
    """
    return ROLE_RANKS.get(role, 0)


def has_role(principal_role: str, required: str) -> bool:
    """True when `principal_role`'s rank meets the `required` role's rank."""
    return role_rank(principal_role) >= role_rank(required)


def meets_any(principal_role: str, required: tuple[str, ...]) -> bool:
    """True when `principal_role` meets at least one of `required` roles."""
    if not required:
        return False
    return any(has_role(principal_role, role) for role in required)


__all__ = [
    "ADMIN_ROLES",
    "ROLE_ADMIN",
    "ROLE_EDITOR",
    "ROLE_OWNER",
    "ROLE_SUPER_ADMIN",
    "ROLE_USER",
    "ROLE_VIEWER",
    "ROLE_RANKS",
    "has_role",
    "meets_any",
    "role_rank",
]
