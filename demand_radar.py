"""
Backward-compatible wrapper.
demand_radar.py → forager.py (v3.0 renamed)
"""

if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from forager import console
    console.print("[yellow]demand_radar.py 已更名为 forager.py, 自动跳转...[/]")
    import forager
