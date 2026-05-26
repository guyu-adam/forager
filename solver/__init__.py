"""
Solver — AI 驱动的需求解决引擎
Pipeline: Planner → Coder → Tester → Packager
"""

import subprocess, json, os, tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Plan:
    """实施计划"""
    files_to_modify: list[str] = field(default_factory=list)
    approach: str = ""
    estimated_loc: int = 0
    risk_level: str = "low"
    test_strategy: str = ""

    def __bool__(self) -> bool:
        return len(self.files_to_modify) > 0


@dataclass
class Solution:
    """解决结果"""
    plan: Optional[Plan] = None
    code: str = ""
    tests: str = ""
    tests_pass: bool = False
    error: str = ""


class Planner:
    """需求 → 结构化实施计划"""

    def plan(self, title: str, body: str, repo_context: dict | None = None) -> Plan:
        """分析 issue, 生成实施计划"""
        text = f"{title}\n{body}".lower()

        plan = Plan()

        # 识别任务类型
        if any(k in text for k in ["bug", "fix", "修复", "error", "报错", "不工作"]):
            plan.approach = "bug_fix"
            plan.risk_level = "low"
            plan.estimated_loc = 20
        elif any(k in text for k in ["test", "测试", "coverage", "覆盖率"]):
            plan.approach = "add_tests"
            plan.risk_level = "low"
            plan.estimated_loc = 50
        elif any(k in text for k in ["feature", "add", "新增", "添加功能", "实现"]):
            plan.approach = "new_feature"
            plan.risk_level = "medium"
            plan.estimated_loc = 80
        elif any(k in text for k in ["refactor", "重构", "migrate", "迁移"]):
            plan.approach = "refactor"
            plan.risk_level = "high"
            plan.estimated_loc = 120
        elif any(k in text for k in ["doc", "文档", "readme"]):
            plan.approach = "docs"
            plan.risk_level = "low"
            plan.estimated_loc = 10
        else:
            plan.approach = "unknown"
            plan.risk_level = "medium"
            plan.estimated_loc = 60

        # 从正文中尝试提取文件路径
        import re
        paths = re.findall(r'(?:src/|lib/|app/|tests?/)[\w/.\-]+\.(?:py|js|ts|rs|go|java)', text)
        plan.files_to_modify = list(set(paths))[:5]

        plan.test_strategy = "run existing test suite, add test for changed behavior"

        return plan


class Coder:
    """计划 → 代码 (委托给本地 LLM / 云端 API)"""

    def generate(self, plan: Plan, issue_title: str, issue_body: str,
                 use_local: bool = True) -> str:
        """基于计划生成代码"""
        prompt = (
            f"Issue: {issue_title}\n{issue_body[:500]}\n\n"
            f"Plan: {plan.approach}\n"
            f"Files: {', '.join(plan.files_to_modify) if plan.files_to_modify else 'unknown'}\n"
            f"Risk: {plan.risk_level}\n\n"
            "Generate the code fix. Output ONLY the corrected code or diff.\n"
        )
        # 实际调用: 通过 Miser 本地 LLM 或 API
        return prompt  # 模板 — 实际调用在 engine.py


class Tester:
    """代码验证 — 沙箱执行测试"""

    def run_tests(self, repo_path: str, test_command: str = "pytest -q") -> bool:
        """在目标 repo 中运行测试"""
        try:
            result = subprocess.run(
                test_command.split(), cwd=repo_path,
                capture_output=True, text=True, timeout=120
            )
            return result.returncode == 0
        except Exception:
            return False

    def syntax_check(self, code: str, language: str = "python") -> bool:
        """语法检查"""
        if language == "python":
            import ast
            try:
                ast.parse(code)
                return True
            except SyntaxError:
                return False
        return True  # 其他语言暂不做


class Packager:
    """代码 + 测试 → 可交付的 patch/diff"""

    def package(self, solution: Solution, repo_path: str = "") -> dict:
        """打包为可交付格式"""
        return {
            "approach": solution.plan.approach if solution.plan else "unknown",
            "code": solution.code,
            "tests": solution.tests,
            "tests_pass": solution.tests_pass,
        }
