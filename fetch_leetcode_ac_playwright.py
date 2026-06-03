#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import pathlib
import time

from playwright.sync_api import sync_playwright


def parse_date(value: str) -> dt.date | None:
    if not value:
        return None
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def to_date_from_ts(timestamp: int) -> dt.date:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).date()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch accepted LeetCode submissions from authenticated browser "
            "context and write JSONL."
        )
    )
    parser.add_argument("--from-date", default="", help="Start date YYYY-MM-DD")
    parser.add_argument("--to-date", default="", help="End date YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=20, help="Page size (default: 20)")
    parser.add_argument("--sleep-seconds", type=float, default=1.5, help="Delay per page")
    parser.add_argument("--sleep", dest="sleep_seconds", type=float, help="Delay per page")
    parser.add_argument(
        "--out",
        default="leetcode_accepted.jsonl",
        help="Output JSONL path (default: leetcode_accepted.jsonl)",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(pathlib.Path.home() / ".leetcode-playwright-profile"),
        help="Persistent browser profile directory",
    )
    return parser.parse_args()


def save_jsonl(rows: list[dict], out: str) -> None:
    path = pathlib.Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"Wrote {len(rows)} rows to {out}")


def main() -> int:
    args = parse_args()
    from_date = parse_date(args.from_date)
    to_date = parse_date(args.to_date)
    if from_date and to_date and from_date > to_date:
        raise RuntimeError("--from-date cannot be after --to-date")

    rows: list[dict] = []
    seen_ids: set[str] = set()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            args.profile_dir,
            headless=False,
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto("https://leetcode.com/problemset/all/", wait_until="domcontentloaded")
        input("If needed, log in to LeetCode in the opened browser, then press Enter...")

        offset = 0
        while True:
            url = f"https://leetcode.com/api/submissions/?offset={offset}&limit={args.limit}"
            result = page.evaluate(
                """async (u) => {
                    const r = await fetch(u, {
                        method: "GET",
                        credentials: "include",
                        headers: {
                            "accept": "application/json, text/plain, */*",
                            "referer": "https://leetcode.com/problemset/all/"
                        }
                    });
                    const text = await r.text();
                    return { status: r.status, text };
                }""",
                url,
            )

            status = int(result["status"])
            text = result["text"]

            if status in (401, 403):
                print(
                    f"LeetCode auth blocked ({status}). Writing partial results and stopping."
                )
                rows.sort(key=lambda x: x["timestamp"])
                save_jsonl(rows, args.out)
                context.close()
                return 0
            if status == 429:
                print("Rate limited; sleeping 60 seconds...")
                time.sleep(60)
                continue
            if status >= 500:
                print(f"Server error {status}; sleeping 30 seconds...")
                time.sleep(30)
                continue

            payload = json.loads(text)
            submissions = payload.get("submissions_dump", [])
            if not submissions:
                break

            for submission in submissions:
                if submission.get("status_display") != "Accepted":
                    continue

                timestamp = int(submission.get("timestamp", "0"))
                if timestamp <= 0:
                    continue

                solved_date = to_date_from_ts(timestamp)
                if from_date and solved_date < from_date:
                    # API is newest-first; once below from-date, we can stop.
                    context.close()
                    rows.sort(key=lambda x: x["timestamp"])
                    save_jsonl(rows, args.out)
                    return 0
                if to_date and solved_date > to_date:
                    continue

                submission_id = str(submission.get("id", "")).strip()
                if not submission_id or submission_id in seen_ids:
                    continue
                seen_ids.add(submission_id)

                rows.append(
                    {
                        "submission_id": submission_id,
                        "timestamp": timestamp,
                        "date": solved_date.isoformat(),
                        "title": submission.get("title", ""),
                        "title_slug": submission.get("title_slug", ""),
                        "lang": submission.get("lang", ""),
                        "status": submission.get("status_display", ""),
                        "runtime": submission.get("runtime", ""),
                    }
                )

            print(f"Fetched offset={offset}; accepted collected={len(rows)}")
            if not payload.get("has_next", False):
                break
            offset += args.limit
            time.sleep(args.sleep_seconds)

        context.close()

    rows.sort(key=lambda x: x["timestamp"])
    save_jsonl(rows, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
