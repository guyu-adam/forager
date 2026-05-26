#!/bin/bash
# Forager — 觅食者启动脚本
# 用法: ./run.sh [模式] [间隔分钟]
#   模式: daemon (持续监控) / once (单次) / forage (觅食循环)
#   默认: daemon, 30分钟间隔

set -e

MODE="${1:-daemon}"
INTERVAL="${2:-30}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

# 自动检测 Python (conda > venv > system)
if command -v conda &>/dev/null && conda env list 2>/dev/null | grep -q "jarves"; then
    PYTHON="conda run -n jarves python3"
elif [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi

echo "Forager — AI 赏金觅食者"
echo "Python: $PYTHON"

case "$MODE" in
    daemon)
        echo "模式: 持续监控, ${INTERVAL}分钟间隔"
        exec $PYTHON forager.py --interval "$INTERVAL"
        ;;
    once)
        echo "模式: 单次扫描"
        exec $PYTHON forager.py --once
        ;;
    forage)
        echo "模式: 觅食循环"
        exec $PYTHON forager.py --forage
        ;;
    dashboard)
        echo "模式: 收益仪表盘"
        exec $PYTHON forager.py --dashboard
        ;;
    *)
        echo "未知模式: $MODE (可用: daemon/once/forage/dashboard)"
        exit 1
        ;;
esac
