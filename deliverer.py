"""
Deliverer — GitHub PR 自动交付 + 状态跟踪
"""

import subprocess, os, tempfile, time, json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class DeliveryResult:
    success: bool
    pr_url: str = ""
    branch: str = ""
    error: str = ""


@dataclass
class PRStatus:
    pr_url: str
    state: str = "open"     # open / merged / closed / changes_requested
    mergeable: bool = False
    check_status: str = ""  # success / failure / pending
    last_checked: str = ""
    auto_fix_attempts: int = 0
    bounty_claimed: bool = False


class PRDeliverer:
    """自动 fork → branch → commit → push → PR"""

    def __init__(self, github_token: str = ""):
        self.token = github_token or os.environ.get("GITHUB_TOKEN", "")
        self.gh_bin = "gh"

    def deliver(self, repo: str, issue_number: int, code: str,
                title: str, description: str = "") -> DeliveryResult:
        """自动提 PR

        Args:
            repo: owner/repo
            issue_number: issue 编号
            code: 代码变更 (patch format or full file content)
            title: PR 标题
            description: PR 描述
        """
        result = DeliveryResult(success=False)

        if not self.token:
            result.error = "GITHUB_TOKEN not set"
            return result

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                branch_name = f"forager/fix-{issue_number}"

                # 1. Clone (via gh)
                subprocess.run(
                    ["gh", "repo", "clone", repo, tmpdir],
                    capture_output=True, check=True, timeout=60,
                    env={**os.environ, "GITHUB_TOKEN": self.token}
                )

                # 2. Create branch
                subprocess.run(
                    ["git", "-C", tmpdir, "checkout", "-b", branch_name],
                    capture_output=True, check=True
                )

                # 3. Apply changes (write code to a patch file or specific file)
                # Simplified: write code to a temp file, let user review
                patch_path = Path(tmpdir) / f"fix-{issue_number}.patch"
                patch_path.write_text(code)

                # 4. Commit
                subprocess.run(
                    ["git", "-C", tmpdir, "add", "-A"],
                    capture_output=True, check=True
                )
                commit_msg = f"fix: {title}\n\nCloses #{issue_number}\n\n{description}"
                subprocess.run(
                    ["git", "-C", tmpdir, "commit", "-m", commit_msg],
                    capture_output=True, check=True
                )

                # 5. Push (gh pushes to origin which is the fork)
                subprocess.run(
                    ["git", "-C", tmpdir, "push", "origin", branch_name],
                    capture_output=True, check=True, timeout=30,
                    env={**os.environ, "GITHUB_TOKEN": self.token}
                )

                # 6. Create PR
                pr_result = subprocess.run(
                    ["gh", "pr", "create",
                     "--repo", repo,
                     "--head", branch_name,
                     "--base", "main",
                     "--title", f"fix: {title}",
                     "--body", f"Closes #{issue_number}\n\n{description}",
                     "--json", "url"],
                    capture_output=True, text=True, timeout=30,
                    env={**os.environ, "GITHUB_TOKEN": self.token}
                )

                if pr_result.returncode == 0:
                    pr_data = json.loads(pr_result.stdout)
                    result.success = True
                    result.pr_url = pr_data.get("url", "")
                    result.branch = branch_name
                else:
                    result.error = pr_result.stderr

            except subprocess.CalledProcessError as e:
                result.error = f"Command failed: {e.stderr}"
            except Exception as e:
                result.error = str(e)

        return result


class PRTracker:
    """PR 状态跟踪"""

    def __init__(self):
        self.gh_bin = "gh"

    def check(self, pr_url: str) -> PRStatus:
        """检查 PR 状态"""
        status = PRStatus(pr_url=pr_url, last_checked=datetime.now().isoformat())

        try:
            r = subprocess.run(
                ["gh", "pr", "view", pr_url, "--json",
                 "state,mergeable,statusCheckRollup"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0:
                data = json.loads(r.stdout)
                status.state = data.get("state", "OPEN").lower()
                status.mergeable = data.get("mergeable", False) or False

                checks = data.get("statusCheckRollup", []) or []
                status.check_status = "success" if all(
                    c.get("status") == "SUCCESS" for c in checks
                ) else ("failure" if any(
                    c.get("status") == "FAILURE" for c in checks
                ) else "pending")
        except Exception:
            pass

        return status

    def is_mergeable(self, pr_url: str) -> bool:
        """检查是否可合并"""
        status = self.check(pr_url)
        return status.state == "open" and status.check_status == "success"
