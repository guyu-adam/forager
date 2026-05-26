"""
Earning Tracker v2 — 收益记录 + 仪表盘 + 自动对账

v2 变更:
  - 新增 auto_reconcile() — 轮询已交付 PR 状态, 检测 merge 自动标记到账
"""

import hashlib
import json
import subprocess
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

import sqlite_utils


@dataclass
class EarningRecord:
    id: str
    issue_url: str
    amount_usd: float
    amount_received: float
    currency: str
    status: str         # found / solved / delivered / verified / paid / lost
    pr_url: str


class EarningTracker:
    """收益记录与统计 (v2: 加自动对账)"""

    def __init__(self, db_path: str = "earnings.db"):
        self.db_path = Path(db_path)
        self.db = sqlite_utils.Database(self.db_path)
        if "earnings" not in self.db.table_names():
            self.db["earnings"].create({
                "id": str, "issue_url": str, "title": str,
                "source": str, "amount_usd": float, "amount_received": float,
                "currency": str, "status": str, "pr_url": str,
                "solved_at": str, "delivered_at": str, "paid_at": str,
                "tx_hash": str, "notes": str,
            }, pk="id")

    def record_found(self, bounty: dict) -> str:
        bid = bounty.get("id", "") or hashlib.md5(
            str(bounty.get("issue_url", "")).encode()).hexdigest()[:16]
        if not self.db["earnings"].count_where("id = ?", [bid]):
            self.db["earnings"].insert({
                "id": bid, "issue_url": bounty.get("issue_url", ""),
                "title": bounty.get("title", ""),
                "source": bounty.get("source", ""),
                "amount_usd": bounty.get("amount_usd", 0),
                "amount_received": 0, "currency": bounty.get("currency", "USD"),
                "status": "found", "pr_url": "",
                "solved_at": "", "delivered_at": "", "paid_at": "",
                "tx_hash": "", "notes": "",
            })
        return bid

    def mark_solved(self, bounty_id: str):
        self.db["earnings"].update(bounty_id, {
            "status": "solved", "solved_at": datetime.now().isoformat()
        })

    def mark_delivered(self, bounty_id: str, pr_url: str):
        self.db["earnings"].update(bounty_id, {
            "status": "delivered", "pr_url": pr_url,
            "delivered_at": datetime.now().isoformat()
        })

    def mark_paid(self, bounty_id: str, amount_received: float,
                  tx_hash: str = ""):
        self.db["earnings"].update(bounty_id, {
            "status": "paid", "amount_received": amount_received,
            "paid_at": datetime.now().isoformat(), "tx_hash": tx_hash
        })

    def mark_lost(self, bounty_id: str, reason: str = ""):
        self.db["earnings"].update(bounty_id, {
            "status": "lost", "notes": reason
        })

    def auto_reconcile(self):
        """v2: 自动对账 — 轮询已交付 PR, 检测 merge 后自动标记到账"""
        from deliverer import PRTracker
        prt = PRTracker()

        delivered = list(self.db["earnings"].rows_where(
            "status = 'delivered' AND pr_url != ''"
        ))

        for row in delivered:
            try:
                status = prt.check(row["pr_url"])
                if status.state == "merged":
                    self.mark_paid(row["id"], row["amount_usd"])
                    print(f"  ✓ {row['title'][:50]} — PR merged, ${row['amount_usd']:.0f} 到账")
                elif status.state == "closed":
                    self.mark_lost(row["id"], "PR closed without merge")
                    print(f"  ✗ {row['title'][:50]} — PR closed, 标记丢失")
            except Exception as e:
                print(f"  ? {row['title'][:50]} — 对账失败: {e}")

        return len(delivered)

    def monthly_report(self, year: int | None = None, month: int | None = None) -> dict:
        now = datetime.now()
        year = year or now.year
        month = month or now.month
        prefix = f"{year}-{month:02d}"

        paid_rows = list(self.db["earnings"].rows_where(
            "paid_at LIKE ?", [f"{prefix}%"]
        ))
        paid = sum(r["amount_received"] for r in paid_rows)

        pending_rows = list(self.db["earnings"].rows_where(
            "status IN ('delivered', 'verified')"
        ))
        pending = sum(r["amount_usd"] for r in pending_rows)

        all_rows = self.db["earnings"].count
        by_status = {}
        for row in self.db["earnings"].rows:
            s = row["status"]
            by_status[s] = by_status.get(s, 0) + 1

        total_paid_ever = sum(
            r["amount_received"] for r in
            self.db["earnings"].rows_where("status = 'paid'")
        )

        return {
            "period": prefix,
            "total_records": all_rows,
            "by_status": by_status,
            "paid_this_month": paid,
            "pending_amount": pending,
            "total_paid_ever": total_paid_ever,
            "delivered_awaiting": len(pending_rows),
        }

    def dashboard(self) -> str:
        r = self.monthly_report()
        return (
            f"  Period: {r['period']}  |  Total: {r['total_records']} records\n"
            f"  By status: {r['by_status']}\n"
            f"  Paid this month: ${r['paid_this_month']:.2f}\n"
            f"  Delivered (awaiting merge): {r['delivered_awaiting']}\n"
            f"  Pending amount: ${r['pending_amount']:.2f}\n"
            f"  Total paid (ever): ${r['total_paid_ever']:.2f}"
        )
