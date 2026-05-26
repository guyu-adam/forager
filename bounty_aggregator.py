"""
Bounty Aggregator — 多平台赏金聚合
Sources: Algora, Opire, Collaborators.build, Expensify, Gitcoin

统一输出标准化的 Bounty 对象，含金额、难度、竞争度。
"""

import hashlib, re, time, requests
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Bounty:
    """标准化赏金对象"""
    id: str
    source: str              # algora / opire / collab / expensify / gitcoin
    title: str
    repo: str                # owner/repo
    issue_url: str
    amount_usd: float        # 统一美元
    currency: str            # USDC / USD / ETH
    labels: list[str] = field(default_factory=list)
    difficulty: str = "unknown"  # easy / medium / hard
    competitors: int = 0     # 已有 PR/评论数
    solvable_by_ai: bool = True
    created_at: str = ""
    body: str = ""

    @property
    def risk_adjusted_value(self) -> float:
        """风险调整后价值"""
        return self.amount_usd / (self.competitors + 1)


def _make_id(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()[:16]


# ── Platform fetchers ──────────────────────────────────────────────────────────

def fetch_algora() -> list[Bounty]:
    """Algora — GitHub issues with '💎 Bounty' label, USDC 支付"""
    bounties = []
    headers = {"Accept": "application/vnd.github+json"}
    try:
        url = ("https://api.github.com/search/issues"
               "?q=label:\"💎 Bounty\"+is:open+is:issue"
               "&sort=created&per_page=30")
        r = requests.get(url, headers=headers, timeout=15)
        for item in r.json().get("items", []):
            amount = _extract_amount(item.get("title", "") + " " + (item.get("body") or ""))
            repo = _extract_repo(item.get("repository_url", ""))
            bounties.append(Bounty(
                id=_make_id(item["html_url"]),
                source="algora",
                title=item.get("title", ""),
                repo=repo,
                issue_url=item["html_url"],
                amount_usd=amount or 25.0,
                currency="USDC",
                labels=[l["name"] for l in item.get("labels", [])],
                competitors=item.get("comments", 0),
                created_at=item.get("created_at", ""),
                body=(item.get("body") or "")[:500],
            ))
        time.sleep(1.2)  # GitHub rate limit
    except Exception as e:
        print(f"  [algora] {e}")
    return bounties


def fetch_opire() -> list[Bounty]:
    """Opire — 公开 API, 无需认证, 返回所有活跃赏金"""
    bounties = []
    try:
        r = requests.get("https://api.opire.dev/rewards", timeout=15)
        for item in r.json():
            amount = float(item.get("amount", 0))
            bounties.append(Bounty(
                id=_make_id(item.get("issue_url", str(item.get("id", "")))),
                source="opire",
                title=item.get("title", ""),
                repo=item.get("repository", ""),
                issue_url=item.get("issue_url", ""),
                amount_usd=amount,
                currency=item.get("currency", "USD"),
                labels=item.get("labels", []),
                competitors=item.get("pull_requests_count", 0),
                created_at=item.get("created_at", ""),
            ))
    except Exception as e:
        print(f"  [opire] {e}")
    return bounties


def fetch_collab() -> list[Bounty]:
    """Collaborators.build — GitHub issues labeled for bounty"""
    bounties = []
    headers = {"Accept": "application/vnd.github+json"}
    try:
        url = ("https://api.github.com/search/issues"
               "?q=label:bounty+is:open+is:issue+org:collaborators-build"
               "&sort=created&per_page=20")
        r = requests.get(url, headers=headers, timeout=15)
        for item in r.json().get("items", []):
            amount = _extract_amount(item.get("title", "") + " " + (item.get("body") or ""))
            repo = _extract_repo(item.get("repository_url", ""))
            bounties.append(Bounty(
                id=_make_id(item["html_url"]),
                source="collab",
                title=item.get("title", ""),
                repo=repo,
                issue_url=item["html_url"],
                amount_usd=amount or 50.0,
                currency="USDC",
                labels=[l["name"] for l in item.get("labels", [])],
                competitors=item.get("comments", 0),
                created_at=item.get("created_at", ""),
                body=(item.get("body") or "")[:500],
            ))
        time.sleep(1.2)
    except Exception as e:
        print(f"  [collab] {e}")
    return bounties


def fetch_expensify() -> list[Bounty]:
    """Expensify — GitHub issues with [$amount] in title, merge 即付"""
    bounties = []
    headers = {"Accept": "application/vnd.github+json"}
    try:
        url = ("https://api.github.com/search/issues"
               "?q=\"Help+Wanted\"+is:open+is:issue+org:Expensify"
               "&sort=created&per_page=20")
        r = requests.get(url, headers=headers, timeout=15)
        for item in r.json().get("items", []):
            title = item.get("title", "")
            # 查找 [$250] 格式的金额标记
            amount = 0.0
            money_match = re.search(r'\[\$(\d+(?:,\d{3})*(?:\.\d+)?)\]', title)
            if money_match:
                amount = float(money_match.group(1).replace(",", ""))
            repo = _extract_repo(item.get("repository_url", ""))
            bounties.append(Bounty(
                id=_make_id(item["html_url"]),
                source="expensify",
                title=title,
                repo=repo,
                issue_url=item["html_url"],
                amount_usd=amount or 50.0,
                currency="USD",
                labels=[l["name"] for l in item.get("labels", [])],
                competitors=item.get("comments", 0),
                created_at=item.get("created_at", ""),
                body=(item.get("body") or "")[:500],
            ))
        time.sleep(1.2)
    except Exception as e:
        print(f"  [expensify] {e}")
    return bounties


def fetch_gitcoin() -> list[Bounty]:
    """Gitcoin — Web3 生态赏金, 金额较大但需 Web3 钱包"""
    bounties = []
    try:
        # Gitcoin Grants API (v2)
        r = requests.get(
            "https://api.gitcoin.co/api/v0.1/bounties/"
            "?is_open=true&order_by=-web3_created&limit=20",
            timeout=15
        )
        for item in r.json().get("results", []):
            amount = float(item.get("value_in_usdt", 0) or 0)
            if amount < 10:
                continue
            bounties.append(Bounty(
                id=_make_id(item.get("url", str(item.get("id", "")))),
                source="gitcoin",
                title=item.get("title", ""),
                repo=item.get("github_url", ""),
                issue_url=item.get("github_url", item.get("url", "")),
                amount_usd=amount,
                currency=item.get("token_name", "USDT"),
                labels=item.get("keywords", []),
                competitors=item.get("interested_count", 0) or 0,
                created_at=item.get("web3_created", ""),
            ))
    except Exception as e:
        print(f"  [gitcoin] {e}")
    return bounties


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_amount(text: str) -> Optional[float]:
    """从标题/正文中提取赏金金额"""
    # [$500], $500 USD, 500 USDC, bounty $200
    patterns = [
        r'\[\$(\d+(?:,\d{3})*(?:\.\d+)?)\]',
        r'\$(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:USD|USDC|USDT)',
        r'(?:bounty|reward).*?\$(\d+(?:,\d{3})*(?:\.\d+)?)',
        r'\$(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:bounty|reward)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return float(m.group(1).replace(",", ""))
    return None


def _extract_repo(repo_url: str) -> str:
    """从 GitHub API repository_url 提取 owner/repo"""
    if not repo_url:
        return ""
    parts = repo_url.rstrip("/").split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return ""


# ── Main aggregator ───────────────────────────────────────────────────────────

class BountyAggregator:
    """多平台赏金聚合器"""

    FETCHERS = {
        "algora": fetch_algora,
        "opire": fetch_opire,
        "collab": fetch_collab,
        "expensify": fetch_expensify,
        "gitcoin": fetch_gitcoin,
    }

    def __init__(self, sources: list[str] | None = None):
        self.sources = sources or list(self.FETCHERS.keys())

    def scan_all(self) -> list[Bounty]:
        """扫描所有平台的赏金, 去重后返回"""
        seen = set()
        all_bounties = []

        for src in self.sources:
            if src in self.FETCHERS:
                try:
                    for b in self.FETCHERS[src]():
                        if b.id not in seen:
                            seen.add(b.id)
                            all_bounties.append(b)
                except Exception:
                    pass

        return all_bounties

    def scan_top(self, n: int = 10) -> list[Bounty]:
        """返回风险调整后最有价值的 n 个赏金"""
        bounties = self.scan_all()
        bounties.sort(key=lambda b: b.risk_adjusted_value, reverse=True)
        return bounties[:n]
