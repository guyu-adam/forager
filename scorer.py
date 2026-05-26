"""
Scorer — 多维度评分引擎
四个维度: pay(付费意愿) + tech_match(技术匹配) + solvability(AI可解决性) + saturation(竞争反比)

用法:
    s = Scorer()
    result = s.score(bounty)  # → ScoreResult(pay=8, tech=7, solvability=9, saturation=6, total=7.5)
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class ScoreResult:
    pay: int = 0           # 0-10
    tech_match: int = 0    # 0-10
    solvability: int = 0   # 0-10 (AI 可解决性)
    saturation: int = 0    # 0-10 (竞争反比, 10=零竞争)
    total: float = 0.0     # 加权总分

    # 细粒度
    price_hint: str = ""
    reasons: list[str] = field(default_factory=list)
    risk_level: str = "medium"           # low / medium / high
    estimated_minutes: int = 30          # 预估耗时

    def __bool__(self) -> bool:
        return self.total >= 4.0


DEFAULT_WEIGHTS = {
    "pay":          0.30,
    "tech_match":   0.20,
    "solvability":  0.30,
    "saturation":   0.20,
}


class Scorer:
    """多维度需求评分器"""

    # ── 付费意愿关键词 (分层) ──
    PAY_TIER1 = ["有偿", "付费求", "悬赏", "代做", "帮做", "明码标价",
                 "bounty $", "bounty €", "usdc", "payout", "prize pool"]
    PAY_TIER2 = ["有偿", "付费", "悬赏", "外包定制", "多少钱", "怎么收费", "接单", "找人帮做",
                 "bounty", "paid", "reward", "hire", "contract", "freelance",
                 "good first issue", "help wanted"]
    PAY_TIER3 = ["帮我", "求助", "想请", "找人帮", "急需",
                 "$", "¥", "元", "块钱", "rmb", "usd", "usdc", "payment"]

    # ── 技术栈关键词 (扩展全覆盖) ──
    TECH_KEYWORDS = [
        # Python 生态
        "python", "django", "flask", "fastapi", "pytest", "selenium", "scrapy",
        # 数据处理
        "excel", "csv", "pandas", "数据处理", "数据清洗", "数据采集", "数据挖掘",
        "爬虫", "抓取", "采集", "批量",
        # 自动化
        "自动化", "脚本", "定时任务", "自动填表", "自动回复",
        # API/后端
        "api", "接口", "rest", "graphql", "后端", "微服务",
        # 前端
        "react", "vue", "next.js", "typescript", "javascript", "前端",
        "tailwind", "组件", "页面",
        # 工具/DevOps
        "docker", "ci/cd", "github actions", "部署", "运维",
        # 数据/AI
        "机器学习", "深度学习", "nlp", "数据分析", "可视化", "报表",
        "ai", "llm", "langchain", "openai", "claude", "chatgpt",
        "统计", "量化",
        # 通用
        "node.js", "rust", "go", "golang", "java", "c++",
    ]

    # ── 不可自动化的硬阻断信号 ──
    HARD_BLOCKERS = [
        "need design review", "requires approval from", "security audit",
        "need access to internal system", "discuss first", "rfc", "proposal needed",
        "on-site", "onsite", "in-person", "面谈", "线下", "驻场",
        "需要到场", "需要驻场",
    ]

    # ── 适合自动化的信号 ──
    AUTO_FRIENDLY = [
        "add test", "fix bug", "update dependency", "refactor",
        "add feature flag", "improve error message", "migrate to",
        "update docs", "add type hint", "add validation", "fix typo",
        "optimize", "add log", "add error handling",
        "写", "修改", "添加", "修复", "优化",
    ]

    # ── 噪声/非外包过滤 ──
    NOISE_PATTERNS = [
        "招聘", "求职", "跳槽", "面试", "内推", "薪资", "工资待遇",
        "拼车", "开源社区", "远程职位", "合伙人招募", "全职招募",
        "offer", "jd", "岗位描述", "依赖更新", "dependabot", "renovate",
        "出租", "出号", "卖号", "出售", "转让账号",
        "分享一个", "推广", "广告", "免费领取",
    ]

    def __init__(self, weights: dict | None = None):
        self.weights = weights or DEFAULT_WEIGHTS

    def score(self, title: str, body: str = "", competitors: int = 0,
              issue_url: str = "", labels: list[str] | None = None) -> ScoreResult:
        """评分一个需求

        Args:
            title: 需求标题
            body: 需求正文
            competitors: 已有竞争者数量 (PR数/评论数)
            issue_url: issue 链接 (用于反饱和分析)
            labels: issue 标签
        """
        text = f"{title} {body}".lower()
        result = ScoreResult()

        # ── 噪声检查 ──
        if any(k in text for k in self.NOISE_PATTERNS):
            result.reasons.append("噪声: 非外包需求")
            return result  # score=0

        # ── 付费意愿 (0-10) ──
        pay_hits_t1 = sum(1 for k in self.PAY_TIER1 if k in text)
        pay_hits_t2 = sum(1 for k in self.PAY_TIER2 if k in text)
        pay_hits_t3 = sum(1 for k in self.PAY_TIER3 if k in text)
        result.pay = min(10, pay_hits_t1 * 4 + pay_hits_t2 * 2 + pay_hits_t3)
        # 美元赏金加分: 支持 $8k / $500 / [$1,200] / bounty $200 等格式
        import re as _re
        # $8k / $8.5k 格式
        km = _re.search(r'\$(\d+(?:\.\d+)?)\s*k', text, _re.I)
        if km:
            amt = float(km.group(1)) * 1000
            result.pay = min(10, result.pay + 4 if amt >= 1000 else (3 if amt >= 500 else 2))
            result.price_hint = f"${amt:.0f}"
        else:
            usd_match = _re.search(
                r'(?:bounty\s*)?\[\s*\$(\d+(?:,\d{3})*(?:\.\d+)?)\s*\]\s*|'
                r'\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:bounty|usd|USD)',
                text, _re.I
            )
            if usd_match:
                amount = usd_match.group(1) or usd_match.group(2)
                if amount:
                    amt = float(amount.replace(",", ""))
                    if amt >= 1000:   result.pay = min(10, result.pay + 4)
                    elif amt >= 500:  result.pay = min(10, result.pay + 3)
                    elif amt >= 100:  result.pay = min(10, result.pay + 2)
                    else:             result.pay = min(10, result.pay + 1)
                    result.price_hint = f"${amt:.0f}"

        # ── 技术匹配 (0-10) ──
        tech_hits = sum(1 for k in self.TECH_KEYWORDS if k in text)
        result.tech_match = min(10, tech_hits * 2)

        # ── AI 可解决性 (0-10) ──
        if any(b in text for b in self.HARD_BLOCKERS):
            result.solvability = 0
            result.reasons.append("不可自动化: 硬阻断")
        else:
            auto_hits = sum(1 for s in self.AUTO_FRIENDLY if s in text)
            result.solvability = min(10, auto_hits * 2 + 3)  # baseline 3
        result.risk_level = "low" if result.solvability >= 7 else ("medium" if result.solvability >= 4 else "high")

        # ── 竞争反比 (0-10) — 越少竞争越高分 ──
        if competitors == 0:
            result.saturation = 10
        elif competitors <= 2:
            result.saturation = 7
        elif competitors <= 5:
            result.saturation = 4
        elif competitors <= 10:
            result.saturation = 2
        else:
            result.saturation = 1

        # ── 废弃赏金加分 (14+天无活动) ──
        # 此逻辑在 forager.py 调用层处理 (需要额外 API 查询)

        # ── 加权总分 ──
        result.total = (
            result.pay          * self.weights["pay"] +
            result.tech_match   * self.weights["tech_match"] +
            result.solvability  * self.weights["solvability"] +
            result.saturation   * self.weights["saturation"]
        )

        # ── 价格估时 ──
        if not result.price_hint:
            result.price_hint = self._estimate_price(text)
        result.estimated_minutes = self._estimate_minutes(text)

        if not result.reasons:
            result.reasons.append(f"pay={result.pay} tech={result.tech_match} "
                                  f"solv={result.solvability} sat={result.saturation}")

        return result

    def _estimate_price(self, text: str) -> str:
        if "爬虫" in text and any(k in text for k in ["验证码", "登录", "反爬"]):
            return "800-2000元"
        if "爬虫" in text:
            return "300-800元"
        if any(k in text for k in ["excel", "报表", "数据清洗"]):
            return "200-600元"
        if any(k in text for k in ["自动化", "批量", "脚本"]):
            return "200-600元"
        if any(k in text for k in ["api", "接口", "对接"]):
            return "500-1500元"
        if any(k in text for k in ["前端", "react", "vue", "页面", "组件"]):
            return "500-3000元"
        if any(k in text for k in ["机器学习", "深度学习", "nlp"]):
            return "1000-5000元"
        return "200-500元"

    def _estimate_minutes(self, text: str) -> int:
        if "bug" in text or "fix" in text or "修复" in text:
            return 30
        if "add test" in text or "添加测试" in text:
            return 20
        if "refactor" in text or "重构" in text:
            return 60
        if "爬虫" in text:
            return 90
        if "前端" in text or "页面" in text:
            return 120
        return 45
