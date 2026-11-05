"""Who is allowed to see which organisation's ledgers.

Kept out of the Streamlit script so the rule can be tested without a browser:
once a deployment maps emails to organisations (`[ocip.orgs]`), an account that
is not in the map is *refused*, not quietly dropped into a default tenant. That
single decision is the difference between an invite-only pilot and a public one.
"""

from __future__ import annotations


def resolve_org(email: str | None, mapping=None, *, default_org: str = "demo",
                allow_unknown: bool = False) -> str | None:
    """Return the org this email belongs to, or None if it is not welcome.

    - mapped email            -> its org, always
    - no mapping at all       -> default_org (single-tenant / dev / sandbox)
    - mapping, unknown email  -> default_org only if allow_unknown, else None
    """
    mapping = mapping or {}
    if email and hasattr(mapping, "get"):
        org = mapping.get(email)
        if org:
            return str(org)
    if mapping and not allow_unknown:
        return None
    return str(default_org)


def mapping_is_enforced(mapping=None, *, allow_unknown: bool = False) -> bool:
    """True when unknown accounts will be turned away."""
    return bool(mapping) and not allow_unknown
