#!/bin/sh
set -e

APP=/app
DATA=/data

mkdir -p $DATA/log $DATA/config $DATA/ssl $DATA/test_case $DATA/public/upload $DATA/public/avatar $DATA/public/website $DATA/user_credentials

if [ ! -f "$DATA/config/secret.key" ]; then
    (umask 077; python -c 'import secrets; print(secrets.token_urlsafe(48))' > "$DATA/config/secret.key")
fi
chmod 600 "$DATA/config/secret.key"

if [ ! -f "$DATA/public/avatar/default.png" ]; then
    cp data/public/avatar/default.png $DATA/public/avatar
fi

if [ ! -f "$DATA/public/website/favicon.ico" ]; then
    cp data/public/website/favicon.ico $DATA/public/website
fi

SSL="$DATA/ssl"
if [ ! -f "$SSL/server.key" ]; then
    openssl req -x509 -newkey rsa:2048 -keyout "$SSL/server.key" -out "$SSL/server.crt" -days 1000 \
        -subj "/C=CN/ST=Beijing/L=Beijing/O=Beijing OnlineJudge Technology Co., Ltd./OU=Service Infrastructure Department/CN=`hostname`" -nodes
fi

cd $APP/deploy/nginx
python $APP/deploy/configure_https.py

if [ -z "$MAX_WORKER_NUM" ]; then
    export CPU_CORE_NUM=$(grep -c ^processor /proc/cpuinfo)
    if [ "$CPU_CORE_NUM" -lt 2 ]; then
        export MAX_WORKER_NUM=2
    else
        export MAX_WORKER_NUM=$(($CPU_CORE_NUM))
    fi
fi

cd $APP/dist
if [ ! -z "$STATIC_CDN_HOST" ]; then
    find . -name "*.*" -type f -exec sed -i "s/__STATIC_CDN_HOST__/\/$STATIC_CDN_HOST/g" {} \;
else
    find . -name "*.*" -type f -exec sed -i "s/__STATIC_CDN_HOST__\///g" {} \;
fi

cd $APP

n=0
until python manage.py migrate --no-input
do
    n=$(($n+1))
    if [ "$n" -ge 5 ]; then
        echo "Database migration failed after 5 attempts; refusing to start services." >&2
        exit 1
    fi
    echo "Failed to migrate, going to retry..."
    sleep 8
done

python manage.py inituser --action=bootstrap
python manage.py shell <<'PY'
import os
from options.options import SysOptions
from judge.dispatcher import sync_judge_server_tasks

token = os.environ.get("JUDGE_SERVER_TOKEN")
if token:
    SysOptions.judge_server_token = token
sync_judge_server_tasks()
PY

grep -q '^spj:' /etc/group || addgroup -g 903 spj
id -u server >/dev/null 2>&1 || adduser -u 900 -S -G spj server

chown -R server:spj $DATA/log $DATA/config $DATA/ssl $DATA/public $APP/dist
chown -R server:spj "$DATA/user_credentials"
chmod 700 "$DATA/user_credentials"
# Workers can create imported testcase directories as soon as Supervisor starts.
chown server:spj "$DATA/test_case"
chmod 710 "$DATA/test_case"

if [ -d "$DATA/test_case" ]; then
    (
        echo "[$(date)] start test_case permission sync"
        find "$DATA/test_case" \( ! -user server -o ! -group spj \) -exec chown server:spj {} \;
        find "$DATA/test_case" -type d ! -perm 710 -exec chmod 710 {} \;
        find "$DATA/test_case" -type f ! -perm 640 -exec chmod 640 {} \;
        echo "[$(date)] finish test_case permission sync"
    ) >> "$DATA/log/test_case_permissions.log" 2>&1 &
fi

exec supervisord -c /app/deploy/supervisord.conf
