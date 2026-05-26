"""
Earning Tracker — 收益记录 + 仪表盘
"""

import sqlite_utils, hashlib
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EarningRecord:
    id: str
    issue_url: str
    amount_usd: float
    amount_received: float
    currency: str
    status: str         # pending / delivered / verified / paid / lost
    pr_url: str
    delivered_at: str
    paid_at: str
    tx_hash: str
    notes: str


class EarningTracker:
    """收益记录与统计"""

    def __init__(self, db_path: str = "earnings.db"):
        self.db = sqlite_utils.Database(Path(db_path))
        if "earnings" not in self.db.table_names():
            self.db["earnings"].create({
                "id": str,
                "issue_url": str,
                "title": str,
                "source": str,
                "amount_usd": float,
                "amount_received": float,
                "currency": str,
                "status": str,         # found / solved / delivered / verified / paid / lost
                "pr_url": str,
                "solved_at": str,
                "delivered_at": str,
                "paid_at": str,
                "tx_hash": str,
                "notes": str,
            }, pk="id")

    def record_found(self, bounty: dict) -> str:
        """记录发现一个赏金"""
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

    def mark_delivered(self, bounty_id: str, pr_url: str):
        """标记已交付"""
        self.db["earnings"].update(bounty_id, {
            "status": "delivered", "pr_url": pr_url,
            "delivered_at": datetime.now().isoformat()
        })

    def mark_paid(self, bounty_id: str, amount_received: float,
                  tx_hash: str = ""):
        """标记已收款"""
        self.db["earnings"].update(bounty_id, {
            "status": "paid", "amount_received": amount_received,
            "paid_at": datetime.now().isoformat(), "tx_hash": tx_hash
        })

    def mark_lost(self, bounty_id: str, reason: str = ""):
        """标记已丢失 (PR rejected, issue closed, etc.)"""
        self.db["earnings"].update(bounty_id, {
            "status": "lost", "notes": reason
        })

    def monthly_report(self, year: int | None = None, month: int | None = None) -> dict:
        """月度收益报告"""
        now = datetime.now()
        year = year or now.year
        month = month or now.month
        prefix = f"{year}-{month:02d}"

        rows = list(self.db["earnings"].rows_where(
            "paid_at LIKE ?", [f"{prefix}%"]
        ))
        paid = sum(r["amount_received"] for r in rows)

        pending_rows = list(self.db["earnings"].rows_where(
            "status IN ('delivered', 'verified')"
        ))
        pending = sum(r["amount_usd"] for r in pending_rows)

        all_rows = self.db["earnings"].count
        by_status = {}
        for row in self.db["earnings"].rows:
            s = row["status"]
            by_status[s] = by_status.get(s, 0) + 1

        return {
            "period": prefix,
            "total_records": all_rows,
            "by_status": by_status,
            "paid_this_month": paid,
            "pending_amount": pending,
            "total_paid_ever": sum(
                r["amount_received"] for r in
                self.db["earnings"].rows_where("status = 'paid'")
            ),
        }

    def dashboard(self) -> str:
        """文本仪表盘"""
        r = self.monthly_report()
        lines = [
            f"  Period: {r['period']}",
            f"  Total records: {r['total_records']}",
            f"  By status: {r['by_status']}",
            f"  Paid this month: ${r['paid_this_month']:.2f}",
            f"  Pending: ${r['pending_amount']:.2f}",
            f"  Total paid (ever): ${r['total_paid_ever']:.2f}",
        ]
        return "\n".join(lines)
