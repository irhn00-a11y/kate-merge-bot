#!/data/data/com.termux/files/usr/bin/bash
# ホーム画面ショートカット：最新版に更新 → 矢印botを1面だけ解いて即終了（広告には触らない）（裏で動く。ターミナルは開かない）
# 押したら5秒以内にゲーム画面へ。盤面が出るまで最大2分待つ
LOG=~/arrow_bot.log
command -v termux-wake-lock >/dev/null && termux-wake-lock   # Termuxを閉じても裏で動き続けるように
toast() { command -v termux-toast >/dev/null && termux-toast -g bottom "$1"; }
cd ~/kate-merge-bot || { toast "kate-merge-bot フォルダがない"; exit 1; }
{
  echo "==== $(date '+%F %T') ===="
  git pull -q --ff-only || echo "git pull 失敗（オフライン？）→ 今の版で実行"
  toast "矢印bot 起動。ゲーム画面へ"
  python -u arrow_bot.py --start-delay 3 --levels 1 --no-ad "$@"   # 1面で即終了・広告には触らない
} >>"$LOG" 2>&1
tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"   # ログは直近500行だけ残す
command -v termux-wake-unlock >/dev/null && termux-wake-unlock
toast "矢印bot 終了: $(grep -E '^合計|停止' "$LOG" | tail -1)"
