#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


LEETCODE_API = "https://leetcode.com/api/submissions/"
STATE_FILE = ".leetcode_synced_ids.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sync LeetCode accepted submissions into git commits "
            "using original submission timestamps."
        )
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Path to git repo (default: current directory).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Page size for LeetCode API pagination (default: 20).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be committed without writing commits.",
    )
    parser.add_argument(
        "--start-date",
        default="",
        help="Only include submissions on/after YYYY-MM-DD.",
    )
    parser.add_argument(
        "--end-date",
        default="",
        help="Only include submissions on/before YYYY-MM-DD.",
    )
    parser.add_argument(
        "--max-commits",
        type=int,
        default=0,
        help="Optional cap for commits created in this run.",
    )
    parser.add_argument(
        "--include-non-accepted",
        action="store_true",
        help="Include non-accepted submissions too (default: accepted only).",
    )
    parser.add_argument(
        "--from-jsonl",
        default="",
        help="Read submissions from JSONL file instead of live LeetCode API.",
    )
    return parser.parse_args()


def env_or_die(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing {name}. Set it in your shell before running this script."
        )
    return value


def csrf_from_env() -> str:
    for name in ("LEETCODE_CSRFTOKEN", "CSRFTOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def build_cookie_header(leetcode_session: str, csrf_token: str) -> str:
    if csrf_token:
        return f"LEETCODE_SESSION={leetcode_session}; csrftoken={csrf_token}"
    return f"LEETCODE_SESSION={leetcode_session}"


def fetch_page(offset: int, limit: int, cookie_header: str, csrf_token: str) -> dict:
    params = urllib.parse.urlencode({"offset": offset, "limit": limit})
    url = f"{LEETCODE_API}?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "Cookie": cookie_header,
            "Referer": "https://leetcode.com/problemset/all/",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://leetcode.com",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        },
        method="GET",
    )
    if csrf_token:
        request.add_header("X-CSRFToken", csrf_token)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        if exc.code == 403:
            raise RuntimeError(
                "LeetCode returned 403 (auth blocked). Re-export fresh "
                "LEETCODE_SESSION and LEETCODE_CSRFTOKEN from the same active "
                "leetcode.com tab, then retry."
            ) from exc
        raise RuntimeError(
            f"LeetCode API request failed ({exc.code}): {detail[:300]}"
        ) from exc


def fetch_page_with_curl(
    offset: int, limit: int, cookie_header: str, csrf_token: str
) -> dict:
    url = f"{LEETCODE_API}?offset={offset}&limit={limit}"
    cmd = [
        "curl",
        "-sS",
        url,
        "-H",
        f"cookie: {cookie_header}",
        "-H",
        "referer: https://leetcode.com/problemset/all/",
        "-H",
        "user-agent: Mozilla/5.0",
    ]
    if csrf_token:
        cmd.extend(["-H", f"x-csrftoken: {csrf_token}"])
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl request failed: {proc.stderr.strip()}")
    body = proc.stdout.strip()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        preview = body[:300]
        raise RuntimeError(f"curl returned non-JSON response: {preview}") from exc
    if isinstance(payload, dict) and payload.get("detail"):
        raise RuntimeError(f"LeetCode API auth error via curl: {payload['detail']}")
    return payload


def fetch_submissions(limit: int, cookie_header: str, csrf_token: str) -> list[dict]:
    submissions: list[dict] = []
    offset = 0
    used_curl_fallback = False
    while True:
        payload = fetch_page_with_curl(offset, limit, cookie_header, csrf_token)
        used_curl_fallback = True
        dump = payload.get("submissions_dump", [])
        if not dump:
            break
        submissions.extend(dump)
        if not payload.get("has_next", False):
            break
        offset += limit
        time.sleep(0.2)
    if used_curl_fallback:
        print("Info: used curl fallback for LeetCode API requests.")
    return submissions


def load_state(path: pathlib.Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(str(x) for x in data)
    except json.JSONDecodeError:
        pass
    return set()


def save_state(path: pathlib.Path, ids: set[str]) -> None:
    path.write_text(json.dumps(sorted(ids), indent=2), encoding="utf-8")


def parse_date(value: str) -> dt.date | None:
    if not value:
        return None
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def load_submissions_from_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        raise RuntimeError(f"JSONL file not found: {path}")
    submissions: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSONL row: {line[:120]}") from exc

            submission = {
                "id": row.get("submission_id", row.get("id", "")),
                "timestamp": str(row.get("timestamp", "0")),
                "title": row.get("title", row.get("title_slug", "problem")),
                "title_slug": row.get("title_slug", "problem"),
                "lang": row.get("lang", "unknown"),
                "runtime": row.get("runtime", ""),
                "status_display": row.get("status", row.get("status_display", "Accepted")),
            }
            submissions.append(submission)
    return submissions


def submission_datetime(submission: dict) -> dt.datetime:
    ts = int(submission.get("timestamp", "0"))
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)


def in_date_window(
    submitted_at: dt.datetime, start_date: dt.date | None, end_date: dt.date | None
) -> bool:
    submission_date = submitted_at.date()
    if start_date and submission_date < start_date:
        return False
    if end_date and submission_date > end_date:
        return False
    return True


def sanitize_slug(value: str) -> str:
    keep = []
    for ch in value.lower().strip():
        if ch.isalnum() or ch in "-_":
            keep.append(ch)
        elif ch in " .":
            keep.append("-")
    slug = "".join(keep).strip("-")
    return slug or "untitled"


def git(args: list[str], cwd: pathlib.Path, env: dict | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git failed")
    return proc.stdout.strip()


def ensure_git_repo(repo: pathlib.Path) -> None:
    try:
        git(["rev-parse", "--is-inside-work-tree"], cwd=repo)
    except RuntimeError as exc:
        raise RuntimeError(f"{repo} is not a git repository.") from exc


def ensure_identity(repo: pathlib.Path) -> None:
    for key in ("user.name", "user.email"):
        try:
            git(["config", "--get", key], cwd=repo)
        except RuntimeError as exc:
            raise RuntimeError(
                f"git {key} is not set in this repo/environment. "
                "Set your GitHub-linked identity first."
            ) from exc


def write_submission_file(repo: pathlib.Path, submission: dict) -> pathlib.Path:
    submitted_at = submission_datetime(submission)
    day = submitted_at.strftime("%Y-%m-%d")
    stamp = submitted_at.strftime("%H%M%S")
    title_slug = sanitize_slug(submission.get("title_slug", "problem"))
    lang = sanitize_slug(submission.get("lang", "unknown"))
    file_name = f"{stamp}-{title_slug}-{lang}.md"

    folder = repo / "leetcode-submissions" / day
    folder.mkdir(parents=True, exist_ok=True)
    out_file = folder / file_name

    submission_id = str(submission.get("id", ""))
    title = submission.get("title", "")
    status = submission.get("status_display", "")
    body = [
        f"# {title}",
        "",
        f"- submission_id: {submission_id}",
        f"- title_slug: {submission.get('title_slug', '')}",
        f"- status: {status}",
        f"- language: {submission.get('lang', '')}",
        f"- runtime: {submission.get('runtime', '')}",
        f"- url: https://leetcode.com/problems/{submission.get('title_slug', '')}/",
        f"- submitted_at_utc: {submitted_at.isoformat()}",
        "",
        "This file was generated by sync_leetcode_to_github.py.",
    ]
    out_file.write_text("\n".join(body) + "\n", encoding="utf-8")
    return out_file


def commit_submission(repo: pathlib.Path, file_path: pathlib.Path, submission: dict) -> None:
    submitted_at = submission_datetime(submission)
    commit_date = submitted_at.strftime("%Y-%m-%dT%H:%M:%S+0000")
    message = (
        f"leetcode: {submission.get('title', 'problem')} "
        f"[{submission.get('lang', 'unknown')}]"
    )
    rel = str(file_path.relative_to(repo))
    git(["add", rel], cwd=repo)

    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = commit_date
    env["GIT_COMMITTER_DATE"] = commit_date
    git(["commit", "-m", message], cwd=repo, env=env)


def main() -> int:
    args = parse_args()
    repo = pathlib.Path(args.repo).resolve()

    ensure_git_repo(repo)
    ensure_identity(repo)

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    if start_date and end_date and start_date > end_date:
        raise RuntimeError("--start-date cannot be after --end-date.")

    if args.from_jsonl:
        all_submissions = load_submissions_from_jsonl(pathlib.Path(args.from_jsonl))
    else:
        leetcode_session = env_or_die("LEETCODE_SESSION")
        csrf_token = csrf_from_env()
        cookie_header = build_cookie_header(leetcode_session, csrf_token)
        all_submissions = fetch_submissions(args.limit, cookie_header, csrf_token)
    state_path = repo / STATE_FILE
    synced_ids = load_state(state_path)
    created = 0
    inspected = 0

    # Oldest first ensures history appears in chronological order.
    all_submissions.sort(key=lambda s: int(s.get("timestamp", "0")))

    for submission in all_submissions:
        inspected += 1
        submission_id = str(submission.get("id", "")).strip()
        if not submission_id or submission_id in synced_ids:
            continue

        status = submission.get("status_display", "")
        if not args.include_non_accepted and status != "Accepted":
            continue

        submitted_at = submission_datetime(submission)
        if not in_date_window(submitted_at, start_date, end_date):
            continue

        if args.max_commits and created >= args.max_commits:
            break

        file_path = write_submission_file(repo, submission)
        if args.dry_run:
            print(
                f"[dry-run] would commit {submission_id} "
                f"{submitted_at.isoformat()} {file_path}"
            )
        else:
            commit_submission(repo, file_path, submission)
            print(
                f"committed {submission_id} {submitted_at.isoformat()} "
                f"{file_path.relative_to(repo)}"
            )
            synced_ids.add(submission_id)
            save_state(state_path, synced_ids)
        created += 1

    print(f"Inspected: {inspected}")
    print(f"New commits {'planned' if args.dry_run else 'created'}: {created}")
    if not args.dry_run:
        print(f"Synced state file: {STATE_FILE}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
