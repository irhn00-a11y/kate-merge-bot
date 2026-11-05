#!/data/data/com.termux/files/usr/bin/bash
# ケイトbot Termux セットアップ（初回のみ）
# 使い方: bash termux_setup.sh
set -e

echo "== パッケージ導入 =="
pkg upgrade -y   # update だけだとライブラリが古いまま残り adb が起動しないことがある
pkg install -y x11-repo
pkg install -y python opencv-python android-tools termux-api || true
python -c "import cv2, numpy; print('OpenCV', cv2.__version__)"

echo "== 共有ストレージ許可（認識画像をギャラリーに保存するため） =="
termux-setup-storage || true

cat <<'MSG'

== 次は手動：自分自身とペアリング ==
1. 設定 → 開発者オプション → 「ワイヤレスデバッグ」ON
   （Xiaomi/POCO系は「USBデバッグ（セキュリティ設定）」もON）
2. 画面分割で 上：設定 / 下：Termux にする
3. ワイヤレスデバッグ →「ペア設定コードによるデバイスのペア設定」
4. Termuxで:  adb pair <表示されたIP>:<ペア用ポート>   → 6桁コード入力
5. ワイヤレスデバッグ画面の「IPアドレスとポート」のポートで:
       adb connect <表示されたIP>:<接続ポート>   （127.0.0.1 でも可のはず）
6. adb devices で device と出れば完了
   ※ペアリングは1回だけ。接続ポートは再起動のたびに変わる

== 起動 ==
   termux-wake-lock
   python kate_merge_bot.py --dry-run      # まず見るだけ
   python kate_merge_bot.py                # 本番（5秒以内にゲームへ切替）
   停止: Termuxに戻って Ctrl+C
MSG
