"""
Forager v3.0 — AI 驱动的开源赏金觅食者
Find → Solve → Deliver → Earn

核心模块:
  forager.py           主入口 — 定时扫描 + 显示
  bounty_aggregator.py  多平台赏金聚合 (Algora/Opire/Collab/Expensify/Gitcoin)
  scorer.py            多维度评分引擎 (pay+tech+solvability+saturation)
  solver/engine.py     AI 解决引擎
  deliverer.py          GitHub PR 自动交付
  earning_tracker.py    收益记录 + 仪表盘

Usage:
  python forager.py --once             单次扫描
  python forager.py                    持续监控 (30min 间隔)
  python forager.py --digest           查看最近24h摘要
  python forager.py --forage           完整觅食循环 (scan→score→solve建议)
  python forager.py --dashboard        收益仪表盘
"""

import sys, time, hashlib, textwrap, argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import feedparser
import requests
import sqlite_utils
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from scorer import Scorer, ScoreResult
from bounty_aggregator import BountyAggregator, Bounty
from earning_tracker import EarningTracker

# ── paths ────────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent
DB   = BASE / "demands.db"
console = Console()


# ── database ──────────────────────────────────────────────────────────────────
def get_db() -> sqlite_utils.Database:
    db = sqlite_utils.Database(DB)
    if "demands" not in db.table_names():
        db["demands"].create({
            "id": str, "source": str, "platform": str,
            "title": str, "url": str, "summary": str,
            "score_pay": int, "score_tech": int,
            "score_solvability": int, "score_saturation": int,
            "score_total": float,
            "price_hint": str, "bounty_amount": float,
            "bounty_currency": str, "competitor_count": int,
            "repo_language": str, "tags": str,
            "found_at": str, "notified": int,
        }, pk="id")
    return db


def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16]


# ── fetchers ──────────────────────────────────────────────────────────────────

V2EX_FEEDS = [
    ("all",  "https://www.v2ex.com/feed/tab/all.xml"),
    ("tech", "https://www.v2ex.com/feed/tab/tech.xml"),
    ("jobs", "https://www.v2ex.com/feed/tab/jobs.xml"),
]

NOISE = ["招聘", "求职", "跳槽", "面试", "内推", "薪资", "工资待遇",
         "拼车", "offer", "jd", "岗位描述", "依赖更新", "dependabot",
         "出号", "卖号", "出售", "转让", "推广", "广告"]


def fetch_v2ex(db: sqlite_utils.Database, scorer: Scorer) -> int:
    """V2EX RSS 抓取"""
    new_count = 0
    for node, url in V2EX_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue
        for entry in feed.entries:
            title = entry.get("title", "")
            link  = entry.get("link", "")
            uid   = make_id(link)
            if db["demands"].count_where("id = ?", [uid]):
                continue
            body = (entry.get("summary", "") or "")[:500]
            scored = scorer.score(title, body)
            if scored.total < 5.0:
                continue
            db["demands"].insert({
                "id": uid, "source": f"v2ex/{node}", "platform": "v2ex",
                "title": title, "url": link, "summary": body[:300],
                "score_pay": scored.pay, "score_tech": scored.tech_match,
                "score_solvability": scored.solvability,
                "score_saturation": scored.saturation,
                "score_total": round(scored.total, 1),
                "price_hint": scored.price_hint, "bounty_amount": 0,
                "bounty_currency": "CNY", "competitor_count": 0,
                "repo_language": "", "tags": node,
                "found_at": datetime.now().isoformat(), "notified": 0,
            })
            new_count += 1
    return new_count


def fetch_v2ex_ddg(db: sqlite_utils.Database, scorer: Scorer) -> int:
    """V2EX DDG 搜索"""
    try:
        from ddgs import DDGS
    except ImportError:
        return 0
    queries = [
        "site:v2ex.com 有偿 python 爬虫", "site:v2ex.com 有偿 自动化 脚本",
        "site:v2ex.com 有偿 excel 数据处理",
        "site:v2ex.com bounty paid freelance",
    ]
    new_count = 0
    try:
        with DDGS() as d:
            for q in queries:
                try:
                    for r in d.text(q, max_results=5):
                        href = r.get("href", "")
                        if "v2ex.com/t/" not in href:
                            continue
                        uid = make_id(href)
                        if db["demands"].count_where("id = ?", [uid]):
                            continue
                        title = r.get("title", "")
                        body = r.get("body", "")[:300]
                        scored = scorer.score(title, body)
                        if scored.total < 5.0:
                            continue
                        db["demands"].insert({
                            "id": uid, "source": "v2ex/ddg", "platform": "v2ex",
                            "title": title, "url": href, "summary": body,
                            "score_pay": scored.pay, "score_tech": scored.tech_match,
                            "score_solvability": scored.solvability,
                            "score_saturation": scored.saturation,
                            "score_total": round(scored.total, 1),
                            "price_hint": scored.price_hint, "bounty_amount": 0,
                            "bounty_currency": "CNY", "competitor_count": 0,
                            "repo_language": "", "tags": q,
                            "found_at": datetime.now().isoformat(), "notified": 0,
                        })
                        new_count += 1
                    time.sleep(1.0)
                except Exception:
                    pass
    except Exception:
        pass
    return new_count


def fetch_github_issues(db: sqlite_utils.Database, scorer: Scorer) -> int:
    """GitHub issue 搜索 — 'help wanted' + 'good first issue' + bounty related"""
    queries = [
        "label:\"good first issue\"+label:bounty+is:open+language:python",
        "label:\"help wanted\"+bounty+is:open+language:python",
    ]
    headers = {"Accept": "application/vnd.github+json"}
    new_count = 0
    for q in queries:
        url = (f"https://api.github.com/search/issues"
               f"?q={requests.utils.quote(q)}&sort=created&per_page=15")
        try:
            r = requests.get(url, headers=headers, timeout=15)
            for item in r.json().get("items", []):
                iurl = item["html_url"]
                uid = make_id(iurl)
                if db["demands"].count_where("id = ?", [uid]):
                    continue
                title = item.get("title", "")
                body = (item.get("body") or "")[:500]
                scored = scorer.score(title, body,
                    competitors=item.get("comments", 0))
                if scored.total < 4.0:
                    continue
                db["demands"].insert({
                    "id": uid, "source": "github", "platform": "github",
                    "title": title, "url": iurl, "summary": body[:300],
                    "score_pay": scored.pay, "score_tech": scored.tech_match,
                    "score_solvability": scored.solvability,
                    "score_saturation": scored.saturation,
                    "score_total": round(scored.total, 1),
                    "price_hint": scored.price_hint, "bounty_amount": 0,
                    "bounty_currency": "USD", "competitor_count": item.get("comments", 0),
                    "repo_language": "python", "tags": "github",
                    "found_at": datetime.now().isoformat(), "notified": 0,
                })
                new_count += 1
        except Exception:
            pass
        time.sleep(1.2)
    return new_count


def fetch_zhihu(db: sqlite_utils.Database, scorer: Scorer) -> int:
    """知乎搜索 — 修复: 加 Cookie 模拟, 降频, 放宽关键词"""
    keywords = ["python 自动化 有偿", "excel 脚本 求助", "数据爬取 有偿"]
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/130.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.zhihu.com/search?type=general",
    }
    new_count = 0
    for kw in keywords:
        url = ("https://www.zhihu.com/api/v4/search_v3"
               f"?t=general&q={requests.utils.quote(kw)}&correction=1&offset=0&limit=8")
        try:
            r = requests.get(url, headers=headers, timeout=15)
            data = r.json()
            for item in data.get("data", []):
                obj = item.get("object", {})
                title = obj.get("title") or obj.get("question", {}).get("title", "")
                if not title:
                    continue
                link = f"https://www.zhihu.com/question/{obj.get('id', '')}"
                uid = make_id(link)
                if db["demands"].count_where("id = ?", [uid]):
                    continue
                excerpt = (obj.get("excerpt") or "")[:300]
                scored = scorer.score(title, excerpt)
                if scored.total < 4.0:
                    continue
                db["demands"].insert({
                    "id": uid, "source": "zhihu", "platform": "zhihu",
                    "title": title, "url": link, "summary": excerpt,
                    "score_pay": scored.pay, "score_tech": scored.tech_match,
                    "score_solvability": scored.solvability,
                    "score_saturation": scored.saturation,
                    "score_total": round(scored.total, 1),
                    "price_hint": scored.price_hint, "bounty_amount": 0,
                    "bounty_currency": "CNY", "competitor_count": 0,
                    "repo_language": "", "tags": kw,
                    "found_at": datetime.now().isoformat(), "notified": 0,
                })
                new_count += 1
        except Exception:
            pass
        time.sleep(1.5)
    return new_count


def fetch_xianyu(db: sqlite_utils.Database, scorer: Scorer) -> int:
    """闲鱼搜索 — 降频, 仅做补充数据源 (P2 优先级)"""
    keywords = ["python脚本 定制", "自动化脚本 代做"]
    headers = {
        "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                       "Version/17.0 Mobile/15E148 Safari/604.1"),
        "Referer": "https://www.goofish.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    new_count = 0
    for kw in keywords:
        url = f"https://www.goofish.com/search?q={requests.utils.quote(kw)}"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            # 闲鱼页面结构常变, 用宽松匹配
            import re
            titles = re.findall(r'"title":"([^"]+)"', r.text)
            for title in titles[:8]:
                title = title.strip()
                if len(title) < 4:
                    continue
                uid = make_id(kw + title)
                if db["demands"].count_where("id = ?", [uid]):
                    continue
                scored = scorer.score(title, kw)
                if scored.total < 4.0:
                    continue
                db["demands"].insert({
                    "id": uid, "source": "xianyu", "platform": "xianyu",
                    "title": title, "url": url, "summary": f"搜索: {kw}",
                    "score_pay": scored.pay, "score_tech": scored.tech_match,
                    "score_solvability": scored.solvability,
                    "score_saturation": scored.saturation,
                    "score_total": round(scored.total, 1),
                    "price_hint": scored.price_hint, "bounty_amount": 0,
                    "bounty_currency": "CNY", "competitor_count": 0,
                    "repo_language": "", "tags": kw,
                    "found_at": datetime.now().isoformat(), "notified": 0,
                })
                new_count += 1
        except Exception:
            pass
        time.sleep(1.5)
    return new_count


def fetch_bounties(db: sqlite_utils.Database, scorer: Scorer) -> int:
    """聚合多平台赏金 (Algora/Opire/Collab/Expensify)"""
    agg = BountyAggregator()
    bounties = agg.scan_all()
    new_count = 0
    for b in bounties:
        uid = b.id
        if db["demands"].count_where("id = ?", [uid]):
            continue
        scored = scorer.score(b.title, b.body, competitors=b.competitors)
        if scored.total < 4.0:
            continue
        db["demands"].insert({
            "id": uid, "source": b.source, "platform": b.source,
            "title": b.title, "url": b.issue_url,
            "summary": b.body[:300],
            "score_pay": scored.pay, "score_tech": scored.tech_match,
            "score_solvability": scored.solvability,
            "score_saturation": scored.saturation,
            "score_total": round(scored.total, 1),
            "price_hint": scored.price_hint,
            "bounty_amount": b.amount_usd,
            "bounty_currency": b.currency,
            "competitor_count": b.competitors,
            "repo_language": "", "tags": ",".join(b.labels),
            "found_at": datetime.now().isoformat(), "notified": 0,
        })
        new_count += 1
    return new_count


# ── display ───────────────────────────────────────────────────────────────────

def show_digest(db: sqlite_utils.Database, hours: int = 24):
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    rows = list(db["demands"].rows_where(
        "found_at > ? ORDER BY score_total DESC LIMIT 25", [cutoff]
    ))
    console.print(f"\n[bold cyan]Forager — 过去{hours}h 摘要[/]")
    console.print(f"共 [bold]{len(rows)}[/] 条机会\n")
    if not rows:
        console.print("[dim]暂无高分需求[/]")
        return
    table = Table(box=box.ROUNDED, show_lines=True, expand=True)
    table.add_column("得分", style="bold yellow", width=5)
    table.add_column("来源", width=12)
    table.add_column("标题", min_width=30)
    table.add_column("估价", width=12)
    table.add_column("赏金", width=10)
    table.add_column("竞争", width=4)
    for row in rows:
        bounty_str = f"${row.get('bounty_amount', 0):.0f}" if row.get("bounty_amount") else "—"
        table.add_row(
            str(row["score_total"]),
            row["source"],
            textwrap.shorten(row["title"], 55),
            row.get("price_hint", "—")[:12],
            bounty_str,
            str(row.get("competitor_count", 0)),
        )
    console.print(table)


# ── main ──────────────────────────────────────────────────────────────────────

def run_once(scorer: Scorer):
    db = get_db()
    console.print(f"[bold green][{datetime.now().strftime('%H:%M:%S')}] 开始觅食...[/]")
    n1 = fetch_v2ex(db, scorer)
    n1b = fetch_v2ex_ddg(db, scorer)
    console.print(f"  V2EX: +{n1} (RSS) +{n1b} (DDG)")
    n2 = fetch_zhihu(db, scorer)
    console.print(f"  知乎: +{n2}")
    n3 = fetch_github_issues(db, scorer)
    console.print(f"  GitHub: +{n3}")
    n4 = fetch_xianyu(db, scorer)
    console.print(f"  闲鱼: +{n4}")
    n5 = fetch_bounties(db, scorer)
    console.print(f"  Bounties (Algora/Opire/Expensify): +{n5}")
    total = db["demands"].count
    console.print(f"  数据库共 {total} 条记录")
    return n1 + n1b + n2 + n3 + n4 + n5


def run_daemon(interval_min: int = 30):
    scorer = Scorer()
    console.print(f"[bold]Forager 启动, 每 {interval_min} 分钟觅食一次[/]  Ctrl-C 退出\n")
    while True:
        run_once(scorer)
        show_digest(get_db(), hours=24)
        console.print(f"\n[dim]下次觅食: {interval_min} 分钟后...[/]\n")
        time.sleep(interval_min * 60)


def cmd_forage(scorer: Scorer):
    """完整觅食循环: scan → score → solve 建议"""
    console.print(Panel("[bold green]Forager — 觅食循环[/]"))
    db = get_db()
    tracker = EarningTracker()

    # 1. Scan
    console.print("\n[bold]1. 扫描赏金...[/]")
    agg = BountyAggregator()
    bounties = agg.scan_top(n=20)
    console.print(f"   发现 {len(bounties)} 个赏金")

    # 2. Score + filter
    console.print("\n[bold]2. 评分筛选...[/]")
    candidates = []
    for b in bounties:
        s = scorer.score(b.title, b.body, competitors=b.competitors)
        if s.total >= 6.0 and s.solvability >= 5:
            candidates.append((b, s))
            tracker.record_found({
                "id": b.id, "issue_url": b.issue_url, "title": b.title,
                "source": b.source, "amount_usd": b.amount_usd,
                "currency": b.currency,
            })
    candidates.sort(key=lambda x: x[0].risk_adjusted_value, reverse=True)
    console.print(f"   过滤后 {len(candidates)} 个候选")

    # 3. Show top
    console.print(f"\n[bold]3. Top 5 推荐:[/]\n")
    for i, (b, s) in enumerate(candidates[:5]):
        console.print(
            f"  [{s.total:.0f}/10] [cyan]{b.title[:70]}[/]\n"
            f"         {b.source} | ${b.amount_usd:.0f} {b.currency} | "
            f"{b.competitors} 竞争者 | {s.risk_level} 风险\n"
            f"         {b.issue_url}\n"
        )

    # 4. Earnings dashboard
    console.print(f"\n[bold]4. 收益仪表盘:[/]")
    console.print(tracker.dashboard())


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Forager — AI 赏金觅食者 v3.0")
    p.add_argument("--once", action="store_true", help="抓一次就退出")
    p.add_argument("--digest", action="store_true", help="只看摘要")
    p.add_argument("--forage", action="store_true", help="完整觅食循环")
    p.add_argument("--dashboard", action="store_true", help="收益仪表盘")
    p.add_argument("--hours", type=int, default=24, help="摘要时间窗口(小时)")
    p.add_argument("--interval", type=int, default=30, help="守护模式间隔(分钟)")
    args = p.parse_args()

    s = Scorer()

    if args.dashboard:
        t = EarningTracker()
        console.print(t.dashboard())
    elif args.forage:
        cmd_forage(s)
    elif args.digest:
        show_digest(get_db(), hours=args.hours)
    elif args.once:
        run_once(s)
        show_digest(get_db(), hours=args.hours)
    else:
        run_daemon(interval_min=args.interval)
