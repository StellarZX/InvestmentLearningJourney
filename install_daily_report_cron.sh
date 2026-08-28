#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRON_MARKER="# InvestmentLearningJourney daily report"
CRON_LINE="0 18 * * 1-5 $ROOT_DIR/daily_report.sh >> $ROOT_DIR/logs/daily_report.log 2>&1 $CRON_MARKER"

mkdir -p "$ROOT_DIR/logs"
CURRENT="$(crontab -l 2>/dev/null || true)"
FILTERED="$(printf '%s\n' "$CURRENT" | sed "/$CRON_MARKER/d; /^CRON_TZ=Europe\/Madrid$/d")"
TMP_CRON="$(mktemp)"
trap 'rm -f "$TMP_CRON"' EXIT
printf '%s\n' "$FILTERED" > "$TMP_CRON"
printf 'CRON_TZ=Europe/Madrid\n%s\n' "$CRON_LINE" >> "$TMP_CRON"
crontab "$TMP_CRON"
echo "已安装：每个工作日（周一至周五）18:00（Europe/Madrid）运行 daily_report.sh"
echo "查看：crontab -l"
