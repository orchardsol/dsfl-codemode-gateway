#!/bin/zsh
# Start or stop one gateway by port, never by process name.
#   ./gw.sh start 18091 geo   |   ./gw.sh start 18090   |   ./gw.sh stop 18091
cd "$(dirname "$0")"
case "$1" in
  stop)  pid=$(lsof -iTCP:$2 -sTCP:LISTEN -t); [ -n "$pid" ] && kill $pid && echo "stopped $2 (pid $pid)" || echo "nothing on $2" ;;
  start) if [ "$3" = "geo" ]; then export GEO=1; fi
         CODEMODE_PORT=$2 nohup uv run python gateway.py > gateway-$2.log 2>&1 &
         for i in $(seq 1 60); do grep -q "Uvicorn running" gateway-$2.log 2>/dev/null && break; sleep 1; done
         grep "Uvicorn running" gateway-$2.log || tail -5 gateway-$2.log ;;
esac
