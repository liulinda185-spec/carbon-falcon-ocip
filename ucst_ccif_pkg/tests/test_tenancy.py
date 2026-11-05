"""The access rule that decides what a signed-in stranger can see."""

from __future__ import annotations

from ucst_ccif.tenancy import mapping_is_enforced, resolve_org


def test_no_mapping_means_single_tenant():
    assert resolve_org("anyone@x.com", {}, default_org="demo") == "demo"


def test_mapped_email_gets_its_org():
    m = {"esg@company-a.com.hk": "company-a"}
    assert resolve_org("esg@company-a.com.hk", m, default_org="cityu") == "company-a"


def test_unmapped_email_is_refused_when_a_list_exists():
    m = {"esg@company-a.com.hk": "company-a"}
    assert resolve_org("stranger@gmail.com", m, default_org="cityu") is None


def test_allow_unknown_restores_the_open_fallback():
    m = {"esg@company-a.com.hk": "company-a"}
    assert resolve_org("stranger@gmail.com", m, default_org="cityu",
                       allow_unknown=True) == "cityu"


def test_missing_email_is_never_admitted_to_a_mapped_tenant():
    m = {"esg@company-a.com.hk": "company-a"}
    assert resolve_org(None, m, default_org="cityu") is None


def test_mapping_is_enforced_only_with_a_list():
    assert not mapping_is_enforced({})
    assert mapping_is_enforced({"a@b.com": "x"})
    assert not mapping_is_enforced({"a@b.com": "x"}, allow_unknown=True)
