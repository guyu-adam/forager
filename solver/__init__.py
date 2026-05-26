"""
Solver — AI 驱动的需求解决引擎 v2
Pipeline: Planner → Coder → Tester → Packager

v2 变更:
  - 新增 FileChange 结构化数据类 (solver ↔ deliverer 统一格式)
  - Solution 增加 file_changes 字段
  - Coder.generate() 改为直接调 Claude API
"""

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class FileChange:
    """结构化文件变更 — solver 输出, deliverer 消费"""
    path: str          # "src/utils/fetcher.py"
    action: str        # "modify" | "create" | "delete"
    content: str       # 完整新文件内容
    test_command: str = ""  # "pytest tests/test_fetcher.py -q"


@dataclass
class Plan:
    """实施计划"""
    files_to_modify: list[str] = field(default_factory=list)
    approach: str = ""
    estimated_loc: int = 0
    risk_level: str = "low"
    test_strategy: str = ""

    def __bool__(self) -> bool:
        return len(self.files_to_modify) > 0 or bool(self.approach)


@dataclass
class Solution:
    """解决结果"""
    plan: Optional[Plan] = None
    code: str = ""                        # 原始 LLM 输出 (保留向后兼容)
    file_changes: list[FileChange] = field(default_factory=list)  # 结构化变更
    tests: str = ""
    tests_pass: bool = False
    explanation: str = ""
    error: str = ""


class Planner:
    """需求 → 结构化实施计划 (v2: 加 LLM 调用)"""

    def plan(self, title: str, body: str, repo_context: dict | None = None,
             use_llm: bool = False) -> Plan:
        text = f"{title}\n{body}".lower()

        plan = Plan()

        # 关键词快速分类 (无需 API)
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
        elif any(k in text for k in ["doc", "文档", "readme", "documentation"]):
            plan.approach = "docs"
            plan.risk_level = "low"
            plan.estimated_loc = 10
        else:
            plan.approach = "unknown"
            plan.risk_level = "medium"
            plan.estimated_loc = 60

        # 从正文提取文件路径
        paths = re.findall(
            r'(?:src/|lib/|app/|tests?/)[\w/.\-]+\.(?:py|js|ts|rs|go|java)',
            text
        )
        plan.files_to_modify = list(set(paths))[:5]
        plan.test_strategy = "run existing test suite, add test for changed behavior"

        return plan


class Coder:
    """计划 → 代码 (直接调 Claude API)"""

    def generate(self, plan: Plan, issue_title: str, issue_body: str,
                 model: str = "claude-sonnet-4-6") -> str:
        """生成修复代码 — 返回 JSON (含结构化 file_changes)

        调用方式:
          1. 有 ANTHROPIC_API_KEY → Claude API
          2. 有 DEEPSEEK_API_KEY   → DeepSeek API (兼容 OpenAI 格式)
          3. 本地 Ollama → Miser ask (fallback, 质量较低)
        """

        prompt = f"""You are fixing a GitHub issue. Output ONLY a JSON object.

Issue title: {issue_title}
Issue body: {issue_body[:1200]}
Plan: {plan.approach}, risk={plan.risk_level}
Files to modify: {', '.join(plan.files_to_modify) if plan.files_to_modify else 'infer from issue'}

Return JSON:
{{
  "files": [
    {{
      "path": "src/utils/example.py",
      "action": "modify",
      "content": "full new file content here",
      "test_command": "pytest tests/test_example.py -q"
    }}
  ],
  "explanation": "one sentence what was changed and why"
}}

Rules:
- action must be "modify", "create", or "delete"
- content must be the COMPLETE new file, not a diff
- Output ONLY the JSON, no markdown fences, no explanation outside JSON."""

        # Try 1: Anthropic API
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
                resp = client.messages.create(
                    model=model,
                    max_tokens=4000,
                    temperature=0.2,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.content[0].text
            except Exception as e:
                pass  # fall through to next provider

        # Try 2: DeepSeek API (OpenAI-compatible)
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if api_key:
            try:
                import requests as _req
                r = _req.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 4000,
                        "temperature": 0.2,
                    },
                    timeout=60,
                )
                return r.json()["choices"][0]["message"]["content"]
            except Exception as e:
                pass

        # Try 3: Local Ollama via Miser
        try:
            import requests as _req
            r = _req.post(
                "http://localhost:7860/ask",
                json={"task": prompt, "from": "forager", "max_tokens": 2000},
                timeout=120,
            )
            resp = r.json()
            return resp.get("result", "") or resp.get("error", "")
        except Exception:
            pass

        return ""


class Tester:
    """代码验证 — 沙箱执行测试"""

    def run_tests(self, repo_path: str, test_command: str = "pytest -q") -> bool:
        try:
            import subprocess
            result = subprocess.run(
                test_command.split(), cwd=repo_path,
                capture_output=True, text=True, timeout=120
            )
            return result.returncode == 0
        except Exception:
            return False

    def syntax_check(self, code: str, language: str = "python") -> bool:
        if language == "python":
            import ast
            try:
                ast.parse(code)
                return True
            except SyntaxError:
                return False
        return True


class Packager:
    """代码 + 测试 → 可交付的 patch/diff"""

    def package(self, solution: 'Solution', repo_path: str = "") -> dict:
        return {
            "approach": solution.plan.approach if solution.plan else "unknown",
            "code": solution.code,
            "tests": solution.tests,
            "tests_pass": solution.tests_pass,
            "file_changes": [
                {"path": fc.path, "action": fc.action, "content": fc.content}
                for fc in solution.file_changes
            ],
        }
