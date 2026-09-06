from app.source_catalog import DEFAULT_JOB_SOURCES


def test_default_source_catalog_contains_startup_and_developer_job_sites() -> None:
    sources = {source.name: source for source in DEFAULT_JOB_SOURCES}

    assert set(sources) == {
        "demoday",
        "groupby",
        "wanted",
        "remember",
        "jumpit",
        "rocketpunch",
        "rallit",
        "jobplanet",
        "saramin",
        "greenhouse",
        "lever",
        "ashby",
        "greeting",
        "ninehire",
    }
    assert sources["demoday"].base_url == "https://demoday.co.kr"
    assert sources["jumpit"].base_url == "https://jumpit.saramin.co.kr"
    assert sources["rocketpunch"].base_url == "https://www.rocketpunch.com"
    assert sources["rallit"].base_url == "https://www.rallit.com"
    assert sources["jobplanet"].base_url == "https://www.jobplanet.co.kr"
    assert sources["remember"].base_url == "https://career.rememberapp.co.kr"
    assert sources["saramin"].base_url == "https://www.saramin.co.kr"
    assert sources["greenhouse"].base_url == "https://job-boards.greenhouse.io"
    assert sources["ninehire"].base_url == "https://ninehire.site"


def test_source_collection_modes_follow_site_policy() -> None:
    sources = {source.name: source for source in DEFAULT_JOB_SOURCES}

    assert sources["wanted"].crawler_type == "browser_assisted"
    assert sources["remember"].crawler_type == "browser_assisted"
    assert sources["groupby"].crawler_type == "browser_assisted"
    assert sources["demoday"].crawler_type == "http"
    assert sources["rocketpunch"].crawler_type == "manual_html"
    assert sources["jumpit"].crawler_type == "http"
    assert sources["rallit"].crawler_type == "http"
    assert sources["jobplanet"].crawler_type == "public_json"
    assert sources["saramin"].crawler_type == "approved_api"
    assert sources["greenhouse"].crawler_type == "public_api"
    assert sources["lever"].crawler_type == "public_api"
    assert sources["ashby"].crawler_type == "public_api"
    assert sources["greeting"].crawler_type == "browser_assisted_multi_host"
    assert sources["ninehire"].crawler_type == "browser_assisted_multi_host"
