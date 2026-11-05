#!/data/data/com.termux/files/usr/bin/bash
# Termux:Widget 用ショートカットを登録（初回のみ。以降の更新はショートカットが自分で git pull する）
set -e
REPO="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.shortcuts/tasks
for f in "$REPO"/shortcuts/*.sh; do
  # tasks/ に置くとターミナルを開かず裏で実行される。
  # 本体はリポジトリ側を呼ぶだけの薄い入口にする（git pull で中身の更新が反映される）
  dst=~/.shortcuts/tasks/"$(basename "$f")"
  printf '#!/data/data/com.termux/files/usr/bin/bash\nexec bash "%s" "$@"\n' "$f" > "$dst"
  chmod +x "$dst"
done
ls ~/.shortcuts/tasks
echo "登録完了。ホーム画面を長押し → ウィジェット → Termux:Widget を置く"
