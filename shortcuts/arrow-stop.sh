#!/data/data/com.termux/files/usr/bin/bash
# ホーム画面ショートカット：矢印botを止める
touch ~/arrow_stop
command -v termux-toast >/dev/null && termux-toast -g bottom "矢印bot 停止を指示"
