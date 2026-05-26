# Forager — AI 驱动的开源赏金觅食者

**Find → Solve → Deliver → Earn**

自动发现 GitHub 赏金 + V2EX 付费需求, AI 解决, 自动提 PR, 收钱。

---

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://python.org)
[![No API Key Required](https://img.shields.io/badge/API%20key-none%20required-brightgreen.svg)](forager.py)
[![Sources: 9](https://img.shields.io/badge/sources-9%20platforms-orange.svg)](#)
[![DB: SQLite](https://img.shields.io/badge/storage-SQLite-lightgrey.svg)](#)

---

## 解决什么问题

技术人想用 AI 赚钱, 但:
1. 不知道哪里有付费需求
2. 找到了不知道怎么高效解决
3. 解决了不知道怎么自动交付

**Forager 是一条完整的流水线**: 发现赏金 → AI 解决 → 自动提 PR → 记录收益。

---

## 商业闭环

```
  发现 (Find)       解决 (Solve)       交付 (Deliver)      收钱 (Earn)
 ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
 │ 9个数据源 │ ──→ │ AI 引擎  │ ──→ │ 自动 PR  │ ──→ │ 收益记录 │
 │ 智能评分 │     │ 成本控制 │     │ 状态跟踪 │     │ 仪表盘   │
 └──────────┘     └──────────┘     └──────────┘     └──────────┘
```

---

## 数据源

| 类型 | 平台 | 说明 |
|---|---|---|
| **赏金平台** | Algora, Opire, Collaborators.build, Expensify, Gitcoin | 标准化的 GitHub bounty, 含金额 |
| **社区** | V2EX (RSS + DDG), 知乎, 闲鱼 | 中文技术外包需求 |
| **GitHub** | `good first issue` + `bounty` 标签 | 开源项目赏金 |

---

## 评分引擎

四维评分 (每维 0-10):

| 维度 | 权重 | 说明 |
|---|---|---|
| **付费意愿** | 30% | 关键词分层匹配 (有偿/悬赏/bounty/$ 等) |
| **技术匹配** | 20% | 全栈关键词覆盖 (Python/React/爬虫/AI 等) |
| **可解决性** | 30% | AI 能否自动化解决 (硬阻断检测 + 自动友好信号) |
| **竞争反比** | 20% | 已有竞争者数量, 废弃赏金加分 |

总分 ≥ 6.0 可尝试自动解决, ≥ 4.0 进入人工审核。

---

## 快速开始

```bash
git clone https://github.com/guyu-adam/forager.git
cd forager
pip install -r requirements.txt

# 单次扫描
python forager.py --once

# 持续监控 (30min 间隔)
python forager.py

# 完整觅食循环 (scan → score → top5)
python forager.py --forage

# 收益仪表盘
python forager.py --dashboard

# 后台运行
bash run.sh
```

---

## 项目结构

```
forager/
  forager.py             主入口 — 定时扫描 + 显示
  bounty_aggregator.py    多平台赏金聚合
  scorer.py              四维评分引擎
  solver/
    __init__.py           Planner → Coder → Tester → Packager
    engine.py             AI 解决引擎主控
  deliverer.py            GitHub PR 自动交付 + 状态跟踪
  earning_tracker.py      收益记录 + 月度仪表盘
  gpu_earner.py           GPU 赚钱调度器 (Vast.ai + Forager + LLM)
  config.yaml             全局配置
  run.sh                  启动脚本
```

---

## 反饱和策略

| 策略 | 说明 | 优先级 |
|---|---|---|
| **废弃赏金收割** | 14+ 天无 PR 的 bounty → 你上 | P0 |
| **零竞争窗口** | 冷门时段发布, 0-2 竞争者 | P1 |
| **深水区专精** | 只做 Python/爬虫/自动化/数据处理 | P1 |
| **小额快反** | $10-50 微赏金, 大号看不上 | P2 |

---

## 成本控制

| 模型 | 用途 | 成本 |
|---|---|---|
| Ollama (qwen3.5:4b) | 代码补全, 简单 fix | $0 |
| DeepSeek | 计划生成, 复杂逻辑 | ~$0.01/次 |
| Claude | 高风险任务 (人工审核) | ~$0.15/次 |

**硬限制**: 单次解决 API 成本 < 赏金额的 10%。

---

## 配合 Miser 使用

Forager 的 solve 层默认使用本地 Miser (localhost:7860) 做代码生成, 零 API 成本。

```bash
# 先启动 Miser
cd ~/miser && nohup python3 miser.py &

# 再跑 Forager
cd ~/forager && python forager.py --forage
```

---

## License

MIT
