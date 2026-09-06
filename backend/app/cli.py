import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from app.config import get_settings
from app.crawler.approved_api import collect_saramin_api
from app.crawler.browser_groupby import collect_groupby_browser
from app.crawler.browser_urls import collect_browser_urls
from app.crawler.job_provider_fetcher import collect_jobplanet_pages
from app.crawler.jobplanet_fetcher import JobPlanetApiClient
from app.crawler.persistence import persist_collected_jobs
from app.crawler.service import collect_http, import_html
from app.db.session import SessionLocal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="get-job")
    commands = parser.add_subparsers(dest="command", required=True)

    crawl = commands.add_parser("crawl", help="collect target developer job postings")
    crawl.add_argument(
        "source",
        choices=[
            "demoday",
            "groupby",
            "wanted",
            "remember",
            "jumpit",
            "rallit",
            "jobplanet",
            "saramin",
        ],
    )
    crawl.add_argument("--url", action="append", default=[])
    crawl.add_argument("--max-jobs", type=int, default=50)
    crawl.add_argument("--headless", action="store_true")

    import_command = commands.add_parser(
        "import-html", help="import a manually saved public detail page"
    )
    import_command.add_argument(
        "source",
        choices=["demoday", "groupby", "wanted", "jumpit", "rocketpunch", "rallit"],
    )
    import_command.add_argument("html_file", type=Path)
    import_command.add_argument("--url", required=True)
    return parser


async def run(args: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    if args.command == "import-html":
        with SessionLocal.begin() as session:
            data, status = import_html(
                session, args.source, args.html_file.read_text(encoding="utf-8"), args.url
            )
            return {"source": args.source, "title": data.title, "status": status}

    if args.source == "groupby":
        jobs = await collect_groupby_browser(
            max_jobs=args.max_jobs,
            headless=args.headless,
            delay_min_seconds=settings.crawler_delay_min_seconds,
            user_agent=settings.crawler_user_agent,
        )
        with SessionLocal.begin() as session:
            counts = persist_collected_jobs(session, "groupby", jobs)
        return {"source": "groupby", "found": len(jobs), **counts}

    if args.source in {"wanted", "remember"}:
        jobs = await collect_browser_urls(
            args.source,
            args.url or None,
            profile_dir=f"playwright-profile/{args.source}",
            max_jobs=args.max_jobs,
            headless=args.headless,
            delay_min_seconds=settings.crawler_delay_min_seconds,
        )
        with SessionLocal.begin() as session:
            counts = persist_collected_jobs(session, args.source, jobs)
        return {"source": args.source, "found": len(jobs), **counts}

    if args.source == "saramin":
        if settings.saramin_api_key is None:
            raise ValueError("SARAMIN_API_KEY가 설정되지 않았습니다")
        jobs = await collect_saramin_api(
            settings.saramin_api_key.get_secret_value(),
            max_jobs=args.max_jobs,
            delay_min_seconds=settings.crawler_delay_min_seconds,
            user_agent=settings.crawler_user_agent,
        )
        with SessionLocal.begin() as session:
            counts = persist_collected_jobs(session, "saramin", jobs)
        return {"source": "saramin", "found": len(jobs), **counts}

    if args.source == "jobplanet":
        jobs = await collect_jobplanet_pages(
            JobPlanetApiClient(),
            max_jobs=args.max_jobs,
            delay_min_seconds=settings.crawler_delay_min_seconds,
        )
        with SessionLocal.begin() as session:
            counts = persist_collected_jobs(session, "jobplanet", jobs)
        return {"source": "jobplanet", "found": len(jobs), **counts}

    with SessionLocal.begin() as session:
        summary = await collect_http(
            session,
            settings,
            args.source,
            urls=args.url or None,
            max_jobs=args.max_jobs,
        )
        return asdict(summary)


def main() -> None:
    args = build_parser().parse_args()
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
