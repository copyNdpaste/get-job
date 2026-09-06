from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JobSourceDefinition:
    name: str
    base_url: str
    crawler_type: str


DEFAULT_JOB_SOURCES = (
    JobSourceDefinition("demoday", "https://demoday.co.kr", "http"),
    JobSourceDefinition("groupby", "https://groupby.kr", "browser_assisted"),
    JobSourceDefinition("wanted", "https://www.wanted.co.kr", "browser_assisted"),
    JobSourceDefinition("remember", "https://career.rememberapp.co.kr", "browser_assisted"),
    JobSourceDefinition("jumpit", "https://jumpit.saramin.co.kr", "http"),
    JobSourceDefinition("rocketpunch", "https://www.rocketpunch.com", "manual_html"),
    JobSourceDefinition("rallit", "https://www.rallit.com", "http"),
    JobSourceDefinition("jobplanet", "https://www.jobplanet.co.kr", "public_json"),
    JobSourceDefinition("saramin", "https://www.saramin.co.kr", "approved_api"),
    JobSourceDefinition("greenhouse", "https://job-boards.greenhouse.io", "public_api"),
    JobSourceDefinition("lever", "https://jobs.lever.co", "public_api"),
    JobSourceDefinition("ashby", "https://jobs.ashbyhq.com", "public_api"),
    JobSourceDefinition("greeting", "https://career.greetinghr.com", "browser_assisted_multi_host"),
    JobSourceDefinition("ninehire", "https://ninehire.site", "browser_assisted_multi_host"),
)
