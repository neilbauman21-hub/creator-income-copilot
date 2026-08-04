#!/bin/bash
# Supervisor: waits for foundation orchestrator, then launches marathon.
cd ~/creator-income-copilot
LOG=build_logs/supervisor.log
echo "[$(date +%H:%M:%S)] Supervisor started. Waiting for foundation orchestrator (proc_44597893c80a)..." >> $LOG

# Wait for foundation orchestrator.sh to finish (it's the parent chain; check by marker)
while pgrep -f "orchestrator.sh" > /dev/null 2>&1; do sleep 20; done
echo "[$(date +%H:%M:%S)] Foundation done. Launching marathon..." >> $LOG
nohup bash ~/creator-income-copilot/marathon.sh >> $LOG 2>&1 &
echo "[$(date +%H:%M:%S)] Marathon launched (pid $!)." >> $LOG
