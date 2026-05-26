"""
gpu_earner.py — RTX 5060 Ti 16GB 赚钱调度器 v2.0
三条收入线:
  1. Vast.ai 挂机出租 GPU (被动)
  2. Forager 觅食循环 (scan → score → solve 建议)
  3. 本地 LLM 推理服务 (Ollama + Miser)

Usage:
  python gpu_earner.py status      GPU 状态 + 收益摘要
  python gpu_earner.py vastai      配置 Vast.ai 出租
  python gpu_earner.py forage      完整觅食循环
  python gpu_earner.py serve       本地推理服务状态
"""

import argparse, subprocess, os, sys, requests
from datetime import datetime

GPU_INFO = {"name": "RTX 5060 Ti", "vram_gb": 16, "cuda": True}


def cmd_status():
    print(f"\n{'='*55}")
    print(f"  GPU 赚钱调度器 v2.0 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    # GPU 状态
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        parts = r.stdout.strip().split(",")
        print(f"\n  GPU    : {parts[0].strip()}")
        print(f"  使用率 : {parts[1].strip()}%   "
              f"显存: {parts[2].strip()}/{parts[3].strip()} MiB  "
              f"温度: {parts[4].strip()}°C")
    except Exception as e:
        print(f"\n  GPU: {e}")

    # Ollama
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        print(f"\n  Ollama : running — {', '.join(models[:3])}")
    except Exception:
        print("\n  Ollama : not running")

    # Miser
    try:
        r = requests.get("http://localhost:7860/health", timeout=3)
        d = r.json()
        print(f"  Miser  : running — {d.get('model', '?')} (status={d.get('status', '?')})")
    except Exception:
        print("  Miser  : not running")

    # Vast.ai
    vastai_key = os.environ.get("VASTAI_API_KEY", "")
    if vastai_key:
        try:
            r = requests.get("https://console.vast.ai/api/v0/instances/",
                             headers={"Authorization": f"Bearer {vastai_key}"}, timeout=5)
            instances = r.json().get("instances", [])
            earning = sum(i.get("actual_cost", 0) for i in instances)
            print(f"\n  Vast.ai: {len(instances)} instances  earning: ${earning:.4f}/hr")
        except Exception as e:
            print(f"\n  Vast.ai: {e}")
    else:
        print("\n  Vast.ai: 未配置 — export VASTAI_API_KEY=your_key")

    # Earnings
    try:
        from earning_tracker import EarningTracker
        t = EarningTracker()
        print(f"\n  [收益]")
        print(t.dashboard())
    except ImportError:
        pass

    print(f"\n{'='*55}\n")


def cmd_vastai():
    print("""
  Vast.ai 出租 RTX 5060 Ti 16GB:
  ─────────────────────────────────────
  1. 注册: https://vast.ai/?ref_id=guyu
  2. pip install vastai && vastai set api-key <key>
  3. 市价: $0.15-0.25/hr → ~$87/month (16hr/day 被动)

  注意: GPU 使用率 <20% 时自动出租, 不影响本地使用。
""")


def cmd_forage():
    """完整觅食循环"""
    sys.path.insert(0, os.path.dirname(__file__))
    from forager import cmd_forage as _forage
    from scorer import Scorer
    _forage(Scorer())


def cmd_serve():
    print("\n  本地推理服务:")
    print("  ─────────────────────────────────────")
    print("  Ollama API:  http://localhost:11434")
    print("  Miser API:   http://localhost:7860")
    try:
        subprocess.run(["nvidia-smi", "--query-gpu=name,memory.free",
                        "--format=csv,noheader"])
    except Exception:
        pass


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="GPU 赚钱调度器 v2.0")
    p.add_argument("cmd", nargs="?", default="status",
                   choices=["status", "vastai", "forage", "serve"])
    args = p.parse_args()
    {"status": cmd_status, "vastai": cmd_vastai,
     "forage": cmd_forage, "serve": cmd_serve}[args.cmd]()
