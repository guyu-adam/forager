"""
Solver Engine v2 — 解决引擎主控
协调 Planner → Coder → Tester → Packager 流水线

v2 变更:
  - solve() 三级 fallback 调真实 LLM (Claude/DeepSeek/Ollama)
  - 输出结构化 Solution.file_changes: list[FileChange]
  - 读 config.yaml 的模型配置
  - 成本硬限制
"""

import json
import os
from pathlib import Path
from typing import Optional

import requests as _req

from . import Planner, Coder, Tester, Packager, Plan, Solution, FileChange


def _load_config():
    """加载 config.yaml (fallback 到默认值)"""
    try:
        import yaml
        cfg_path = Path(__file__).parent.parent / "config.yaml"
        if cfg_path.exists():
            with open(cfg_path) as f:
                return yaml.safe_load(f)
    except Exception:
        pass
    return {}


def _extract_issue_number(url: str) -> int:
    import re
    m = re.search(r'/issues?/(\d+)', url)
    return int(m.group(1)) if m else 0


class SolverEngine:
    """AI 解决引擎 — 主控 (v2: 支持真实 LLM 调用)"""

    def __init__(self, max_cost_ratio: float = 0.10, min_confidence: float = 0.75):
        self.planner = Planner()
        self.tester = Tester()
        self.packager = Packager()
        self.max_cost_ratio = max_cost_ratio
        self.min_confidence = min_confidence
        self.cfg = _load_config()

    def solve(self, title: str, body: str, repo: str = "",
              issue_url: str = "", bounty_amount_usd: float = 0) -> Solution:
        """解决一个需求 — 完整流水线

        Returns:
            Solution with plan, code, file_changes (结构化, deliverer 可直接消费)
        """
        solution = Solution()

        # Step 1: 规划
        solution.plan = self.planner.plan(title, body)

        # Step 2: 成本检查
        estimated_api_cost = solution.plan.estimated_loc * 0.0003
        if bounty_amount_usd > 0 and estimated_api_cost > bounty_amount_usd * self.max_cost_ratio:
            solution.error = (f"成本超限: est ${estimated_api_cost:.4f} > "
                             f"${bounty_amount_usd * self.max_cost_ratio:.2f} (上限)")
            return solution

        # Step 3: 生成代码 (三级 fallback: Claude → DeepSeek → Ollama)
        coder = Coder()
        raw_output = coder.generate(solution.plan, title, body)

        if not raw_output:
            solution.error = "所有 LLM 后端不可用 (Claude/DeepSeek/Ollama)"
            return solution

        solution.code = raw_output

        # Step 4: 解析 JSON → 结构化 FileChange
        try:
            # 清理 markdown fence
            cleaned = raw_output.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
            data = json.loads(cleaned)
            solution.file_changes = [
                FileChange(
                    path=fc.get("path", ""),
                    action=fc.get("action", "modify"),
                    content=fc.get("content", ""),
                    test_command=fc.get("test_command", ""),
                )
                for fc in data.get("files", [])
            ]
            solution.explanation = data.get("explanation", "")
        except (json.JSONDecodeError, KeyError) as e:
            # 解析失败: 尝试从原始输出中提取有用内容
            solution.error = f"LLM 输出格式错误, 无法解析 JSON: {e}"
            solution.file_changes = []

        # Step 5: 语法检查
        if solution.file_changes:
            all_ok = all(
                self.tester.syntax_check(fc.content) for fc in solution.file_changes
            )
            solution.tests_pass = all_ok

        return solution

    def estimate_chances(self, title: str, body: str) -> float:
        """估算成功解决概率 (0-1)"""
        plan = self.planner.plan(title, body)
        if plan.risk_level == "high":
            return 0.3
        if plan.risk_level == "medium":
            return 0.6
        return 0.85
