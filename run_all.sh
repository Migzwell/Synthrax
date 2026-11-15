#!/usr/bin/env bash
# Starts the whole Synthrax demo: the clock and all three sites, in one terminal,
# then opens the three screens in your browser.
# Run from the project folder:  ./run_all.sh        Stop everything: Ctrl+C
# Start the demo fresh:          ./run_all.sh --fresh
cd "$(dirname "$0")"
source .venv/bin/activate

if [ "$1" = "--fresh" ]; then
  rm -f data/*.db
  echo "Deleted old databases: starting fresh from the seed."
fi

trap 'echo; echo "Stopping Synthrax..."; kill 0' EXIT

python -m control.clock_server > /dev/null 2>&1 &
sleep 1
for site in carehome gp pharmacy; do
  python -u -m node.main --node "$site" 2>&1 | while IFS= read -r line; do echo "[$site] $line"; done &
done
sleep 5

echo
echo "Synthrax is running:"
echo "  Care home  http://localhost:8001"
echo "  GP         http://localhost:8002"
echo "  Pharmacy   http://localhost:8003"
echo "Press Ctrl+C to stop everything."

python -m webbrowser -t http://localhost:8001 > /dev/null
python -m webbrowser -t http://localhost:8002 > /dev/null
python -m webbrowser -t http://localhost:8003 > /dev/null
wait