# leetcode-commit-mirror

Mirror your own LeetCode accepted submissions into a Git repository with historically accurate commit dates, so your GitHub contribution graph reflects real practice activity.

## What it does

- Opens a real browser session (via Playwright) so you log in to LeetCode yourself
- Fetches your accepted submissions with pagination and rate-limiting
- Exports them to a portable `accepted.jsonl` file
- Creates one Git commit per submission, dated to the original submission time
- Deduplicates across runs via `.leetcode_synced_ids.json`
- Optionally runs on a daily schedule via GitHub Actions (no browser needed)

## What it does NOT do

- Bypass LeetCode authentication or scrape other users
- Generate fake practice history or fabricate contributions
- Submit code to LeetCode on your behalf

## Quickstart

```bash
git clone https://github.com/jeremyky/leetcode-commit-mirror.git
cd leetcode-commit-mirror

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Step 1: Export your submissions

```bash
python3 fetch_leetcode_ac_playwright.py --out accepted.jsonl
```

A browser window opens. Log in to LeetCode if needed, then press Enter in the terminal.

### Step 2: Preview commits (dry run)

```bash
python3 sync_leetcode_to_github.py --from-jsonl accepted.jsonl --dry-run
```

### Step 3: Create commits

```bash
python3 sync_leetcode_to_github.py --from-jsonl accepted.jsonl
```

### Step 4: Push

```bash
git push origin main
```

Your contribution graph may take a while to update after pushing — in my case it took about **2 hours** before the green squares appeared.

## Backfill a specific date range

```bash
python3 fetch_leetcode_ac_playwright.py \
  --from-date 2025-01-01 \
  --to-date 2025-06-30 \
  --out accepted.jsonl

python3 sync_leetcode_to_github.py --from-jsonl accepted.jsonl
git push
```

## Options

### `fetch_leetcode_ac_playwright.py`

| Flag | Default | Description |
|---|---|---|
| `--from-date` | *(none)* | Only include submissions on/after `YYYY-MM-DD` |
| `--to-date` | *(none)* | Only include submissions on/before `YYYY-MM-DD` |
| `--out` | `leetcode_accepted.jsonl` | Output JSONL file path |
| `--limit` | `20` | Page size per API request |
| `--sleep` | `1.5` | Seconds between paginated requests |
| `--profile-dir` | `~/.leetcode-playwright-profile` | Persistent browser profile directory |

### `sync_leetcode_to_github.py`

| Flag | Default | Description |
|---|---|---|
| `--from-jsonl` | *(none)* | Import submissions from JSONL instead of live API |
| `--repo` | `.` | Path to the target git repository |
| `--dry-run` | `false` | Preview commits without writing them |
| `--start-date` | *(none)* | Filter: only commit submissions on/after `YYYY-MM-DD` |
| `--end-date` | *(none)* | Filter: only commit submissions on/before `YYYY-MM-DD` |
| `--max-commits` | `0` (no limit) | Cap the number of commits created per run |
| `--include-non-accepted` | `false` | Include non-accepted submissions too |

## How GitHub contribution graphs work

- Commits count on your graph when pushed to the repo's **default branch** and the commit email matches a **verified email** on your GitHub account.
- For private repos, enable **"Include private contributions on my profile"** in GitHub profile settings.
- The graph can take a while to update after pushing — often a few minutes, but sometimes **1–2 hours** (especially after a large backfill of historical commits).

## Contribution graph honesty

This tool creates commits with historical dates that match your real LeetCode accepted submissions. It is intended to represent genuine practice history, not fabricate activity. Do not use this tool to create fake contributions.

## Compliance

- This tool accesses only your own LeetCode account through a normal browser session.
- Keep request rates low (the default `--sleep 1.5` is conservative).
- LeetCode's Terms of Service restrict automated scraping. This tool uses minimal, low-volume requests for personal data backup. Stop immediately if LeetCode blocks or rate-limits you.
- No LeetCode data (cookies, sessions, submission code) is stored or transmitted anywhere besides your local machine and your own Git repository.

## Troubleshooting

**403 "You do not have permission"**
- Make sure you are logged in to LeetCode in the Playwright browser window before pressing Enter.
- Try increasing `--sleep` to `3` or `4` seconds.
- Your session may have expired. Close the browser profile directory (`rm -rf ~/.leetcode-playwright-profile`) and re-run to get a fresh login.

**Commits don't show on contribution graph**
- Verify `git config user.email` matches a verified email on your GitHub account.
- Make sure commits are on the default branch (`main`).
- For private repos, enable "Include private contributions" in GitHub settings.

**Rate limited (429)**
- The script automatically waits 60 seconds and retries. If it persists, increase `--sleep`.

## Make sure your commits actually show up

After pushing, GitHub can take a while to refresh your graph. Give it at least **1–2 hours** before assuming something is wrong — a large backfill of backdated commits can be slow to propagate. If it still doesn't show after that, check these:

**1. Email mismatch (most common)**
Run `git config user.email` — the output must exactly match a verified email in your [GitHub Email Settings](https://github.com/settings/emails). If it doesn't, either add that email to GitHub or update your local config:
```bash
git config user.email "your-github-email@example.com"
```
Then re-run the sync and push again. GitHub retroactively credits commits once the email is verified.

**2. Wrong branch**
GitHub only counts commits on your repo's default branch (`main` or `master`). Confirm with `git branch` that you're on `main` before pushing.

**3. Private repo**
If this repo is private, go to your GitHub profile → Contribution settings → check **Include private contributions on my profile**.

**4. Forked repo**
Commits in a fork don't count unless merged upstream. Use a repo you own outright (not a fork).

**5. Timezone cutoff**
GitHub uses UTC for day boundaries. A commit timestamped at 11 PM your local time may appear on the next UTC day in your graph — this is expected.

## Automated sync via GitHub Actions

A workflow at `.github/workflows/sync.yml` runs the sync on a daily cron schedule (6 AM UTC by default) and can also be triggered manually from the Actions tab.

**How it works:** The workflow calls `sync_leetcode_to_github.py` directly using your LeetCode session cookie stored as a GitHub secret — no browser/Playwright needed. It commits any new submissions (with their original timestamps) and pushes to `main`.

**Recommended setup:** Use this workflow in the repo where you want mirrored commits to land — typically a **private** repo you own, not a public fork of this tool.

**One-time setup:**

1. Go to your repo → **Settings → Secrets and variables → Actions → New repository secret** and add:

   | Secret name | Value |
   |---|---|
   | `LEETCODE_SESSION` | Your `LEETCODE_SESSION` cookie value from leetcode.com |
   | `LEETCODE_CSRFTOKEN` | Your `csrftoken` cookie value (optional but recommended) |
   | `GIT_EMAIL` | The email verified on your GitHub account (must match for graph credit) |
   | `GIT_NAME` | Your name (e.g. `jeremyky`) |

2. To find your cookie values: log into leetcode.com → open DevTools → Application → Cookies → copy `LEETCODE_SESSION` and `csrftoken`.

3. Enable the workflow under the **Actions** tab if prompted.

**The catch:** LeetCode session cookies expire every few weeks. When the workflow starts failing with a 403, grab a fresh cookie from your browser and update the `LEETCODE_SESSION` secret.

**Adjusting the schedule:** Edit the `cron` line in `.github/workflows/sync.yml`. The format is standard cron — `'0 6 * * *'` means daily at 6 AM UTC. Use [crontab.guru](https://crontab.guru) to build a custom schedule.

## License

[MIT](LICENSE)
