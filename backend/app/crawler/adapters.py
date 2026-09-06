import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode, urljoin, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag

from app.crawler.domain import CollectedJob
from app.crawler.hiring_process import analyze_hiring_process, process_items_from_value
from app.crawler.job_profile import JOB_SEARCH_TERMS
from app.crawler.normalization import normalize_text, stable_external_id
from app.crawler.relevance import extract_tech_stack


@dataclass(frozen=True, slots=True)
class SitePolicy:
    source_name: str
    base_url: str
    collection_mode: str
    list_urls: tuple[str, ...]
    job_path_pattern: str
    search_terms: tuple[str, ...] = JOB_SEARCH_TERMS


DEMODAY_SEARCH_PAGES = 5


def _demoday_list_urls() -> tuple[str, ...]:
    return tuple(
        f"https://demoday.co.kr/recruits?{urlencode({'page': page, 'search': term})}"
        for term in JOB_SEARCH_TERMS
        for page in range(1, DEMODAY_SEARCH_PAGES + 1)
    )


POLICIES = {
    "demoday": SitePolicy(
        "demoday",
        "https://demoday.co.kr",
        "http",
        _demoday_list_urls(),
        r"/recruits/\d+",
    ),
    "groupby": SitePolicy("groupby", "https://groupby.kr", "browser", (), r"/positions/\d+"),
    "wanted": SitePolicy("wanted", "https://www.wanted.co.kr", "browser_url", (), r"/wd/\d+"),
    "remember": SitePolicy(
        "remember",
        "https://career.rememberapp.co.kr",
        "browser",
        ("https://career.rememberapp.co.kr/job/postings",),
        r"/job/postings/\d+",
    ),
    "jumpit": SitePolicy(
        "jumpit",
        "https://jumpit.saramin.co.kr",
        "http",
        ("https://jumpit.saramin.co.kr/sitemap/sitemap_position_view_1.xml",),
        r"/position/\d+",
    ),
    "rocketpunch": SitePolicy(
        "rocketpunch",
        "https://www.rocketpunch.com",
        "manual_html",
        (),
        r"/jobs/\d+(?:/[^?#]+)?",
    ),
    "rallit": SitePolicy(
        "rallit",
        "https://www.rallit.com",
        "http",
        ("https://www.rallit.com/server-sitemap.xml",),
        r"/positions/\d+(?:/[^?#]+)?",
    ),
}

SECTION_LABELS = {
    "main_tasks": ("주요업무", "주요 업무"),
    "requirements": ("자격요건", "자격 요건"),
    "preferred_requirements": ("우대사항", "우대 사항"),
    "benefits": ("복지 및 혜택", "혜택 및 복지", "복지 및 근무환경"),
    "hiring_process": (
        "채용절차",
        "채용 절차",
        "전형절차",
        "전형 절차",
        "채용 프로세스",
        "채용 과정",
        "전형 과정",
        "합류 여정",
        "합류 과정",
    ),
}
PROCESS_FIELD_NAMES = (
    "hiringProcess",
    "hiring_process",
    "hire_rounds",
    "recruitmentProcess",
    "recruitment_process",
    "recruitProcess",
    "recruit_process",
)


def _split_items(text: str) -> list[str]:
    values = []
    for part in re.split(r"[\r\n]+|(?=\s*[•·]\s+)", text):
        cleaned = normalize_text(re.sub(r"^[\s•·\-]+", "", part))
        if cleaned:
            values.append(cleaned)
    return values


def _section(soup: BeautifulSoup, labels: tuple[str, ...]) -> list[str]:
    label_set = {normalize_text(label) for label in labels}
    node = soup.find(
        lambda tag: (
            isinstance(tag, Tag)
            and tag.name in {"h2", "h3", "h4", "dt", "div", "p", "span"}
            and normalize_text(tag.get_text(" ", strip=True)) in label_set
        )
    )
    if not isinstance(node, Tag):
        return []
    if node.name == "dt":
        container = node.find_next_sibling("dd")
        return _split_items(container.get_text("\n", strip=True)) if container else []

    parent = node.parent
    if isinstance(parent, Tag):
        editor = parent.select_one(".ql-editor")
        if editor:
            return _split_items(editor.get_text("\n", strip=True))
        following = []
        for sibling in node.next_siblings:
            if isinstance(sibling, Tag) and sibling.name in {"h2", "h3", "h4", "dt"}:
                break
            if isinstance(sibling, Tag) and sibling.name not in {"style", "script", "svg"}:
                following.append(sibling.get_text("\n", strip=True))
        if following:
            return _split_items("\n".join(following))
        parent_text = parent.get_text("\n", strip=True)
        return _split_items(parent_text.removeprefix(node.get_text(" ", strip=True)))
    return []


def _json_ld_job(soup: BeautifulSoup) -> dict[str, object]:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or str(script.get("textcontent") or "{}"))
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                return candidate
    return {}


def _rallit_position(soup: BeautifulSoup) -> dict[str, object]:
    script = soup.select_one("script#__NEXT_DATA__")
    if script is None or not script.string:
        return {}
    try:
        data = json.loads(script.string)
        position = data["props"]["pageProps"]["position"]
        return position if isinstance(position, dict) else {}
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def _first_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            value = normalize_text(node.get_text(" ", strip=True))
            if value:
                return value
    return None


class SiteAdapter:
    def __init__(self, policy: SitePolicy):
        self.policy = policy

    def listing_urls(self, html: str, page_url: str) -> list[str]:
        found: list[str] = []
        if self.policy.source_name == "demoday":
            candidates = [
                f"/recruits/{job_id}"
                for job_id in re.findall(r"(?:https://demoday\.co\.kr)?/recruits/(\d+)", html)
            ]
        elif "<urlset" in html or "<sitemapindex" in html:
            root = ElementTree.fromstring(html)
            candidates = [
                node.text
                for node in root.iter()
                if node.tag.rsplit("}", 1)[-1] == "loc" and node.text
            ]
        else:
            soup = BeautifulSoup(html, "html.parser")
            candidates = [link.get("href") for link in soup.select("a[href]")]
        for href in candidates:
            if not href:
                continue
            url = urljoin(page_url, href)
            if urlsplit(url).netloc == urlsplit(self.policy.base_url).netloc and re.search(
                self.policy.job_path_pattern, urlsplit(url).path
            ):
                if url not in found:
                    found.append(url)
        return found

    def parse_detail(self, html: str, url: str) -> CollectedJob:
        soup = BeautifulSoup(html, "html.parser")
        ld = _json_ld_job(soup)
        rallit_position = _rallit_position(soup) if self.policy.source_name == "rallit" else {}
        title = str(
            self._title(soup) or ""
            if self.policy.source_name == "demoday"
            else ld.get("title") or self._title(soup) or ""
        )
        company_name = self._company(soup, ld)
        if not title or not company_name:
            raise ValueError(f"{self.policy.source_name} detail page is missing title/company")

        sections = {name: _section(soup, labels) for name, labels in SECTION_LABELS.items()}
        source_tech_stack = []
        if self.policy.source_name == "jumpit":
            source_tech_stack = _section(soup, ("기술스택", "기술 스택", "기술 스택 • 툴"))
        elif self.policy.source_name == "demoday":
            skills = ld.get("skills")
            if isinstance(skills, str):
                source_tech_stack = [
                    normalized
                    for item in skills.split(",")
                    if (normalized := normalize_text(item))
                ]
            elif isinstance(skills, list):
                source_tech_stack = [
                    normalized
                    for item in skills
                    if (normalized := normalize_text(str(item or "")))
                ]
        if rallit_position:
            rallit_sections = {
                "main_tasks": "responsibilities",
                "requirements": "basicQualifications",
                "preferred_requirements": "preferredQualifications",
                "benefits": "benefits",
            }
            for section_name, field_name in rallit_sections.items():
                fragment = BeautifulSoup(str(rallit_position.get(field_name) or ""), "html.parser")
                sections[section_name] = _split_items(fragment.get_text("\n", strip=True))
            for field_name in PROCESS_FIELD_NAMES:
                sections["hiring_process"].extend(
                    process_items_from_value(rallit_position.get(field_name))
                )
        description_text = self._description(soup, ld)
        if rallit_position:
            detail_parts = [
                BeautifulSoup(str(rallit_position.get(field) or ""), "html.parser").get_text(
                    " ", strip=True
                )
                for field in (
                    "description",
                    "responsibilities",
                    "basicQualifications",
                    "preferredQualifications",
                    "benefits",
                    *PROCESS_FIELD_NAMES,
                )
            ]
            skills = rallit_position.get("jobSkillKeywords")
            if isinstance(skills, list):
                source_tech_stack.extend(
                    normalized
                    for skill in skills
                    if (normalized := normalize_text(str(skill or "")))
                )
                detail_parts.extend(source_tech_stack)
            description_text = normalize_text(" ".join([description_text, *detail_parts]))
        elif source_tech_stack:
            description_text = normalize_text("\n".join([description_text, *source_tech_stack]))
        source_tech_stack = list(dict.fromkeys(source_tech_stack))
        experience = self._experience(soup, description_text, ld)
        location = self._location(soup, ld)
        posted_at = self._datetime(
            ld.get("datePosted")
            or rallit_position.get("approvedAt")
            or rallit_position.get("startedAt")
        )
        deadline = self._deadline(ld)
        detected_stack = extract_tech_stack(
            "\n".join([title, description_text, *sum(sections.values(), [])])
        )
        tech_stack = list(dict.fromkeys([*source_tech_stack, *detected_stack]))
        process_info = analyze_hiring_process(sections["hiring_process"])
        return CollectedJob(
            source_name=self.policy.source_name,
            external_job_id=stable_external_id(self.policy.source_name, url, title, company_name),
            company_name=company_name,
            title=title,
            url=url,
            description_raw=html,
            description_text=description_text,
            main_tasks=sections["main_tasks"],
            requirements=sections["requirements"],
            preferred_requirements=sections["preferred_requirements"],
            benefits=sections["benefits"],
            tech_stack=tech_stack,
            hiring_process=list(process_info.steps),
            has_coding_test=process_info.has_coding_test,
            interview_count=process_info.interview_count,
            experience_text=experience,
            location=location,
            employment_type=str(ld.get("employmentType")) if ld.get("employmentType") else None,
            posted_at=posted_at,
            deadline_at=deadline,
        )

    def parse_api_detail(self, payload: dict[str, object], url: str) -> CollectedJob:
        if self.policy.source_name != "wanted":
            raise ValueError(f"{self.policy.source_name} does not support API detail parsing")
        wrapped_data = payload.get("data")
        root = wrapped_data if isinstance(wrapped_data, dict) else payload
        job = root.get("job")
        if not isinstance(job, dict):
            raise ValueError("wanted API response is missing job")
        company = job.get("company")
        detail = job.get("detail")
        if not isinstance(company, dict) or not isinstance(detail, dict):
            raise ValueError("wanted API response is missing company/detail")
        title = normalize_text(str(job.get("position") or detail.get("position") or ""))
        company_name = normalize_text(str(company.get("name") or ""))
        if not title or not company_name:
            raise ValueError("wanted API response is missing title/company")

        section_fields = {
            "main_tasks": "main_tasks",
            "requirements": "requirements",
            "preferred_requirements": "preferred_points",
            "benefits": "benefits",
        }
        sections = {
            name: _split_items(str(detail.get(field) or ""))
            for name, field in section_fields.items()
        }
        process_items: list[str] = []
        for container in (detail, job):
            for field_name in PROCESS_FIELD_NAMES:
                process_items.extend(process_items_from_value(container.get(field_name)))
        process_info = analyze_hiring_process(process_items)
        description_parts = [
            str(detail.get(field) or "")
            for field in ("intro", "main_tasks", "requirements", "preferred_points", "benefits")
        ]
        skill_tags = job.get("skill_tags")
        skill_names = []
        if isinstance(skill_tags, list):
            for tag in skill_tags:
                if not isinstance(tag, dict):
                    continue
                value = normalize_text(str(tag.get("text") or tag.get("title") or ""))
                if value and value not in skill_names:
                    skill_names.append(value)
        description_text = normalize_text(
            "\n".join([*description_parts, *process_info.steps, *skill_names])
        )
        address = job.get("address")
        location = None
        if isinstance(address, dict):
            location = (
                normalize_text(str(address.get("full_location") or address.get("location") or ""))
                or None
            )
        annual_from = job.get("annual_from")
        annual_to = job.get("annual_to")
        employment_type = normalize_text(str(job.get("employment_type") or "")) or None
        employment_note = normalize_text(str(job.get("employment_note") or ""))
        experience = None
        if isinstance(annual_from, int) and isinstance(annual_to, int):
            if annual_to >= 100:
                experience = f"경력 {annual_from}년 이상"
            else:
                experience = (
                    f"신입-경력 {annual_to}년"
                    if annual_from == 0
                    else f"경력 {annual_from}-{annual_to}년"
                )
        elif isinstance(annual_from, int):
            experience = f"경력 {annual_from}년 이상"
        is_intern = (
            "인턴" in title
            or "인턴" in employment_note
            or (employment_type or "").casefold() in {"intern", "internship"}
        )
        if is_intern:
            experience = f"인턴 · {experience}" if experience else "인턴"

        detected_stack = extract_tech_stack("\n".join([title, description_text, *skill_names]))
        tech_stack = list(dict.fromkeys([*skill_names, *detected_stack]))
        return CollectedJob(
            source_name="wanted",
            external_job_id=str(
                job.get("id") or stable_external_id("wanted", url, title, company_name)
            ),
            company_name=company_name,
            title=title,
            url=url,
            description_raw=json.dumps(payload, ensure_ascii=False),
            description_text=description_text,
            main_tasks=sections["main_tasks"],
            requirements=sections["requirements"],
            preferred_requirements=sections["preferred_requirements"],
            benefits=sections["benefits"],
            tech_stack=tech_stack,
            hiring_process=list(process_info.steps),
            has_coding_test=process_info.has_coding_test,
            interview_count=process_info.interview_count,
            experience_text=experience,
            location=location,
            employment_type=employment_type,
            deadline_at=self._datetime(job.get("due_time")),
        )

    def _title(self, soup: BeautifulSoup) -> str | None:
        title = _first_text(soup, ("main h1", "h1"))
        if title:
            return title
        meta = soup.select_one('meta[property="og:title"]')
        return normalize_text(str(meta.get("content"))) if meta and meta.get("content") else None

    @staticmethod
    def _description(soup: BeautifulSoup, ld: dict[str, object]) -> str:
        if ld.get("description"):
            fragment = BeautifulSoup(str(ld["description"]), "html.parser")
            return normalize_text(fragment.get_text(" ", strip=True))
        main = soup.select_one("main")
        scoped = BeautifulSoup(str(main or soup), "html.parser")
        cutoff = scoped.find(
            lambda tag: (
                isinstance(tag, Tag)
                and tag.name in {"h2", "h3"}
                and normalize_text(tag.get_text(" ", strip=True))
                in {"비슷한 채용 공고", "가장 인기있는 공고"}
            )
        )
        if isinstance(cutoff, Tag):
            for sibling in list(cutoff.next_siblings):
                if isinstance(sibling, Tag):
                    sibling.decompose()
            cutoff.decompose()
        for unwanted in scoped.select("style, script, svg"):
            unwanted.decompose()
        return normalize_text(scoped.get_text(" ", strip=True))

    def _company(self, soup: BeautifulSoup, ld: dict[str, object]) -> str:
        organization = ld.get("hiringOrganization")
        if isinstance(organization, dict) and organization.get("name"):
            return normalize_text(str(organization["name"]))
        selectors = {
            "wanted": ('a[href*="/company/"]',),
            "jumpit": ('a[href*="/company/"]',),
            "rocketpunch": ('a[href*="/companies/"]',),
            "rallit": ('a[href*="/companies/"] h2', 'a[href*="/companies/"]'),
            "groupby": ('img[alt$=" 로고"]',),
            "demoday": ("main h1",),
            "remember": (
                'a[href*="/companies/"]',
                'a[href*="/company/"]',
                "main [data-company-name]",
            ),
        }[self.policy.source_name]
        value = _first_text(soup, selectors)
        if value:
            return value.removesuffix(" 로고")
        image = soup.select_one('img[alt$=" 로고"]')
        if image and image.get("alt"):
            return str(image["alt"]).removesuffix(" 로고")
        return ""

    def _experience(
        self, soup: BeautifulSoup, text: str, ld: dict[str, object] | None = None
    ) -> str | None:
        if self.policy.source_name == "demoday" and ld:
            requirement = normalize_text(str(ld.get("experienceRequirements") or ""))
            range_match = re.fullmatch(r"(\d+)\s*[-~]\s*(\d+)", requirement)
            minimum_match = re.fullmatch(r"(\d+)\s*\+", requirement)
            if range_match:
                return f"경력 {range_match.group(1)}-{range_match.group(2)}년"
            if minimum_match:
                return f"경력 {minimum_match.group(1)}년 이상"
            if requirement.casefold() in {"entry", "entry_level", "신입"}:
                return "신입"
            if requirement.casefold() in {"irrelevant", "경력무관", "경력 무관"}:
                return "경력무관"
        if self.policy.source_name == "rallit":
            levels = _rallit_position(soup).get("jobLevels")
            labels = {
                "NEWCOMER": "신입",
                "JUNIOR": "주니어 (1~3년)",
                "MIDDLE": "미들 (4~8년)",
                "SENIOR": "시니어 (9년 이상)",
                "IRRELEVANT": "경력무관",
            }
            if isinstance(levels, list):
                rendered = [labels[level] for level in levels if level in labels]
                if rendered:
                    return ", ".join(rendered)
        if self.policy.source_name in {"jumpit", "rallit"}:
            values = _section(soup, ("경력",))
            if values:
                return values[0]
        match = re.search(
            r"(?:경력\s*)?(?:신입\s*[-~]\s*)?\d+\s*(?:[-~]\s*\d+)?\s*년(?:\s*(?:이상|이하))?", text
        )
        return normalize_text(match.group()) if match else None

    def _location(self, soup: BeautifulSoup, ld: dict[str, object]) -> str | None:
        location = ld.get("jobLocation")
        if isinstance(location, dict):
            address = location.get("address")
            if isinstance(address, dict):
                parts = [
                    str(address.get(key, ""))
                    for key in ("addressRegion", "addressLocality", "streetAddress")
                ]
                value = normalize_text(" ".join(dict.fromkeys(part for part in parts if part)))
                if value:
                    return value
        values = _section(soup, ("근무지역", "근무 지역"))
        for value in values:
            if value not in {"주소 복사", "지도보기", "주소복사"}:
                return value
        return None

    @staticmethod
    def _deadline(ld: dict[str, object]) -> datetime | None:
        return SiteAdapter._datetime(ld.get("validThrough"))

    @staticmethod
    def _datetime(value: object) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None


ADAPTERS = {name: SiteAdapter(policy) for name, policy in POLICIES.items()}


def get_adapter(source_name: str) -> SiteAdapter:
    try:
        return ADAPTERS[source_name]
    except KeyError as exc:
        raise ValueError(f"unsupported source: {source_name}") from exc


def validate_source_url(source_name: str, url: str) -> str:
    try:
        policy = POLICIES[source_name]
    except KeyError as exc:
        raise ValueError(f"unsupported source: {source_name}") from exc
    parts = urlsplit(url)
    expected = urlsplit(policy.base_url)
    if parts.scheme != "https":
        raise ValueError(f"{source_name} URL must use https")
    if parts.username or parts.password:
        raise ValueError(f"{source_name} URL must not include credentials")
    if parts.hostname != expected.hostname:
        raise ValueError(f"{source_name} URL host must be {expected.hostname}")
    if parts.port not in {None, 443}:
        raise ValueError(f"{source_name} URL must not use a custom port")
    if not re.fullmatch(rf"(?:{policy.job_path_pattern})/?", parts.path):
        raise ValueError(f"{source_name} URL is not a supported public job detail URL")
    return url
