#!/usr/bin/env python3
"""Create, reopen, comment on, and close GitHub issues for daily audit regressions."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def _request(method: str, url: str, token: str, payload: dict | None = None) -> dict | list:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "arcis-daily-repo-audit",
        },
    )
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else {}


def _list_issues(repo: str, token: str) -> list[dict]:
    issues = []
    page = 1
    while True:
        batch = _request(
            "GET",
            f"https://api.github.com/repos/{repo}/issues?state=all&per_page=100&page={page}",
            token,
        )
        if not batch:
            break
        issues.extend(batch)
        page += 1
    return [row for row in issues if "pull_request" not in row]


def _build_issue_title(task: dict) -> str:
    return f"[Daily Repo Audit] Unexpected regression in {task['title']}"


def _build_issue_body(repo: str, summary: dict, task: dict) -> str:
    lines = [
        f"Automated daily repo audit detected an unexpected regression in `{task['task_id']}`.",
        "",
        f"- Repository: `{repo}`",
        f"- Date (UTC): `{summary['date_utc']}`",
        f"- Overall audit status: `{summary['overall_status']}`",
        f"- Task: `{task['title']}`",
        f"- Command: `{task['command']}`",
    ]
    if summary.get("run_url"):
        lines.append(f"- Run URL: {summary['run_url']}")
    lines.extend(
        [
            "",
            "Latest summary:",
            "",
            task.get("summary", "No summary available."),
        ]
    )
    if task.get("output_excerpt"):
        lines.extend(["", "```text", task["output_excerpt"], "```"])
    lines.extend(
        [
            "",
            "This issue is managed by `scripts/sync_daily_repo_audit_issues.py`.",
        ]
    )
    return "\n".join(lines).strip()


def _build_recovery_comment(summary: dict, task: dict) -> str:
    lines = [
        f"Daily repo audit no longer sees this regression in `{task['task_id']}`.",
        "",
        f"- Date (UTC): `{summary['date_utc']}`",
        f"- Overall audit status: `{summary['overall_status']}`",
    ]
    if summary.get("run_url"):
        lines.append(f"- Run URL: {summary['run_url']}")
    return "\n".join(lines)


def _build_regression_comment(summary: dict, task: dict) -> str:
    lines = [
        f"Regression still present in the daily repo audit for `{task['task_id']}`.",
        "",
        f"- Date (UTC): `{summary['date_utc']}`",
        f"- Command: `{task['command']}`",
    ]
    if summary.get("run_url"):
        lines.append(f"- Run URL: {summary['run_url']}")
    lines.extend(["", task.get("summary", "No summary available.")])
    if task.get("output_excerpt"):
        lines.extend(["", "```text", task["output_excerpt"], "```"])
    return "\n".join(lines)


def _comment(repo: str, token: str, issue_number: int, body: str) -> None:
    _request(
        "POST",
        f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
        token,
        {"body": body},
    )


def _create_issue(repo: str, token: str, title: str, body: str) -> dict:
    return _request(
        "POST",
        f"https://api.github.com/repos/{repo}/issues",
        token,
        {"title": title, "body": body},
    )


def _update_issue(repo: str, token: str, issue_number: int, payload: dict) -> dict:
    return _request(
        "PATCH",
        f"https://api.github.com/repos/{repo}/issues/{issue_number}",
        token,
        payload,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync daily repo audit regressions to GitHub issues")
    parser.add_argument("--summary", required=True, help="Path to summary.json from the audit run")
    args = parser.parse_args()

    summary_path = Path(args.summary)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token:
        print("GITHUB_REPOSITORY or GITHUB_TOKEN not set; skipping issue sync")
        return 0

    issues = _list_issues(repo, token)
    by_title = {issue["title"]: issue for issue in issues}

    current_unexpected = {
        _build_issue_title(task): task for task in summary.get("unexpected_failures", [])
    }

    for title, task in current_unexpected.items():
        body = _build_issue_body(repo, summary, task)
        existing = by_title.get(title)
        if existing:
            issue_number = existing["number"]
            if existing.get("state") == "closed":
                _update_issue(repo, token, issue_number, {"state": "open", "body": body})
            else:
                _update_issue(repo, token, issue_number, {"body": body})
            _comment(repo, token, issue_number, _build_regression_comment(summary, task))
            print(f"UPDATED #{issue_number} {title}")
        else:
            created = _create_issue(repo, token, title, body)
            issue_number = created["number"]
            _comment(repo, token, issue_number, _build_regression_comment(summary, task))
            print(f"CREATED #{issue_number} {title}")

    managed_prefix = "[Daily Repo Audit] Unexpected regression in "
    for issue in issues:
        title = issue["title"]
        if not title.startswith(managed_prefix):
            continue
        if title in current_unexpected:
            continue
        if issue.get("state") != "open":
            continue
        task_title = title.removeprefix(managed_prefix)
        recovered_task = {"task_id": task_title, "title": task_title}
        _comment(repo, token, issue["number"], _build_recovery_comment(summary, recovered_task))
        _update_issue(repo, token, issue["number"], {"state": "closed"})
        print(f"CLOSED #{issue['number']} {title}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
