#!/bin/zsh
cd -- "$(dirname -- "$0")/ruoyi-vue-pro" || exit 1
python3 .local-dev/manage.py start
navio_result=$?
printf "\n按回车关闭此窗口…"
read -r navio_reply
exit "$navio_result"
