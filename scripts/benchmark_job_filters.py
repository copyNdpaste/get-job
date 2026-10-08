"""Measure local API filter latency without storing job or candidate content."""
import argparse
import json
import statistics
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

SCENARIOS = {
    "unfiltered": {"sort": "fit", "limit": 50},
    "python": {"tech": "Python", "sort": "fit", "limit": 50},
    "career": {"experience": "career", "min_years": 3, "max_years": 8,
               "sort": "fit", "limit": 50},
    "combined": {"tech": "Python", "exclude_tech": ["Java", "Spring Boot"],
                 "experience": "career", "min_years": 3, "max_years": 8,
                 "min_fit_score": 65, "sort": "fit", "limit": 50},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if urlsplit(args.base_url).hostname not in {"localhost", "127.0.0.1"}:
        parser.error("Only the local job API is supported")
    if not 1 <= args.samples <= 20:
        parser.error("samples must be between 1 and 20")
    metrics = {}
    for name, params in SCENARIOS.items():
        timings = []
        total = returned = None
        for _ in range(args.samples):
            start = time.perf_counter()
            with urlopen(args.base_url + "/api/jobs?" + urlencode(params, doseq=True),
                         timeout=120) as response:
                payload = json.load(response)
            timings.append(round((time.perf_counter() - start) * 1000, 2))
            total, returned = payload["total"], len(payload["items"])
        metrics[name] = {"median_ms": round(statistics.median(timings), 2),
                         "samples_ms": timings, "total": total, "returned": returned}
        print(name, json.dumps(metrics[name]), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(metrics, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
