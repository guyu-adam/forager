"""
Solver Engine — 解决引擎主控
协调 Planner → Coder → Tester → Packager 流水线
"""

import requests as _req
from pathlib import Path

from . import Planner, Coder, Tester, Packager, Plan, Solution

# Miser endpoint
MISER = "http://localhost:7860"


class SolverEngine:
    """AI 解决引擎 — 主控"""

    def __init__(self, max_cost_ratio: float = 0.10, min_confidence: float = 0.75,
                 use_local_llm: bool = True):
        self.planner = Planner()
        self.coder = Coder()
        self.tester = Tester()
        self.packager = Packager()
        self.max_cost_ratio = max_cost_ratio
        self.min_confidence = min_confidence
        self.use_local_llm = use_local_llm

    def solve(self, title: str, body: str, repo: str = "",
              issue_url: str = "", bounty_amount_usd: float = 0) -> Solution:
        """解决一个需求

        Args:
            title: issue 标题
            body: issue 正文
            repo: owner/repo
            issue_url: issue 链接
            bounty_amount_usd: 赏金金额

        Returns:
            Solution with plan, code, tests
        """
        solution = Solution()

        # Step 1: 规划
        solution.plan = self.planner.plan(title, body)

        # Step 2: 成本检查
        estimated_api_cost = solution.plan.estimated_loc * 0.0003  # ~$0.0003/LOC
        if bounty_amount_usd > 0 and estimated_api_cost > bounty_amount_usd * self.max_cost_ratio:
            solution.error = (f"成本超限: est ${estimated_api_cost:.2f} > "
                             f"${bounty_amount_usd * self.max_cost_ratio:.2f} (上限)")
            return solution

        # Step 3: 生成代码 (本地 LLM)
        if self.use_local_llm:
            prompt = self.coder.generate(solution.plan, title, body)
            try:
                r = _req.post(f"{MISER}/codegen",
                             json={"task": prompt, "lang": "python"}, timeout=60)
                solution.code = r.json().get("code", "") or r.json().get("error", "")
            except Exception as e:
                solution.code = f"// LLM unavailable: {e}"

        # Step 4: 语法检查
        if solution.code:
            solution.tests_pass = self.tester.syntax_check(solution.code)

        return solution

    def estimate_chances(self, title: str, body: str) -> float:
        """估算成功解决概率 (0-1)"""
        plan = self.planner.plan(title, body)
        if plan.risk_level == "high":
            return 0.3
        if plan.risk_level == "medium":
            return 0.6
        return 0.85
