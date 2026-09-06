from urllib.parse import urlsplit

from app.ecosystem_catalog import DEFAULT_ECOSYSTEM_ORGANIZATIONS


def test_ecosystem_catalog_covers_ac_vc_and_impact_organizations() -> None:
    slugs = [organization.slug for organization in DEFAULT_ECOSYSTEM_ORGANIZATIONS]
    organization_types = [
        organization.organization_type for organization in DEFAULT_ECOSYSTEM_ORGANIZATIONS
    ]

    assert len(slugs) >= 18
    assert len(slugs) == len(set(slugs))
    assert "newkids-investment" in slugs
    assert any("AC" in organization_type for organization_type in organization_types)
    assert any("VC" in organization_type for organization_type in organization_types)
    assert any("임팩트" in organization_type for organization_type in organization_types)
    assert {"dito-investment", "vcs-notices", "vcs-venture-mart"}.issubset(slugs)


def test_ecosystem_catalog_has_product_specific_fit_metadata() -> None:
    organizations = {item.slug: item for item in DEFAULT_ECOSYSTEM_ORGANIZATIONS}

    assert organizations["mashup-ventures"].fit_score >= 90
    assert "소프트웨어" in organizations["mashup-ventures"].focus_tags
    assert organizations["cnttech"].source_url == (
        "https://www.vcs.go.kr/web/portal/investor/view/OP20180020"
    )
    assert organizations["vcs-venture-mart"].program_url is not None


def test_monitored_program_pages_are_https() -> None:
    monitored = [
        organization
        for organization in DEFAULT_ECOSYSTEM_ORGANIZATIONS
        if organization.program_url is not None
    ]

    assert "newkids-investment" in {organization.slug for organization in monitored}
    assert all(
        urlsplit(organization.program_url or "").scheme == "https" for organization in monitored
    )
