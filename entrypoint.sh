
echo "$CRON_SCHEDULE cd /app && python -m garrison" > crontab
crontab crontab

crond -f
