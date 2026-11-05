#!/usr/bin/env python3
"""arrow_bot の実機ループを仮想ゲームで回すテスト（ADB不要）

- 画面取得 → 実スクショから、抜けた棒を背景色で塗りつぶした画像を返す
- タップ   → 押された棒の頭の先に他の棒が残っていたら「ミス」として数える
  使い方: python tools/arrow_sim.py docs/arrow_board.jpg [arrow_botの引数…]
  AFTER=same でクリア後も盤面そっくりの画面が出続ける最悪ケース、AFTER=next で次の面
  TRUTH=docs/arrow_board.jpg で正解を別画像から作る（頭を消した画像の検証用）
  ANIM=3 で押した棒が画面取得3回のあいだ残る（抜けるアニメ）
  MANUAL=1 で人が読めない棒を手で押す役をする
  AD=1 でクリア後に広告（戻る3回目で閉じる）、AD=btn で戻るが効かずスキップボタンでだけ閉じる広告
  STORE=1 で1回目の戻るでストアに飛ばされる、AWAY=1 でクリア後しばらくClaudeアプリが前面
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import arrow_bot as ab  # noqa: E402
import kate_merge_bot as kb  # noqa: E402

src = cv2.imread(sys.argv[1])
# TRUTH=きれいな画像：正解（棒の配置）はそこから作り、botには sys.argv[1]（頭を消した等の画像）を見せる
board, _ = ab.parse_board(cv2.imread(os.environ["TRUTH"]) if os.environ.get("TRUTH") else src)
bars, P, pitch = board["bars"], board["P"], board["pitch"]
bg = tuple(int(v) for v in np.median(src[400:500, 40:1040].reshape(-1, 3), 0))
gone, misses, taps = set(), 0, 0
moving = {}   # ANIM=n：押した棒は画面取得n回のあいだ残り、他の棒の進路を塞ぎ続ける（抜けるアニメ）
ANIM = int(os.environ.get("ANIM", "0"))
blank_reads = 0
occ = {u: i for i, b in enumerate(bars) for u in b["path"]}


def bar_at(x, y):
    c, r = round((x - P(0, 0)[0]) / pitch), round((y - P(0, 0)[1]) / pitch)
    i = occ.get((c, r))
    return None if i is None or i in gone else i


cleared = 0


def levels_cleared():
    return cleared + 1


AD_IMG = cv2.imread(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "ad_admob_skip.png"))


manual_wait = 0


def fake_screencap():
    global manual_wait
    for i in list(moving):
        moving[i] -= 1
        if moving[i] <= 0:
            del moving[i]
            gone.add(i)
    if os.environ.get("MANUAL") and len(gone) < len(bars):
        # 人が押す役：bot が読めない棒しか残っていない時、押せる棒を1本抜く
        manual_wait += 1
        if manual_wait > 3:
            for i in range(len(bars)):
                if i not in gone and bar_free(i):
                    gone.add(i)
                    print("  （人が手で押した）")
                    break
            manual_wait = 0
    if ad_state["on"] and os.environ.get("AD") == "btn":
        return AD_IMG.copy()
    img = src.copy()
    if len(gone) == len(bars) and not moving and AD and ad_state["shown"] < levels_cleared():
        ad_state.update(on=True, backs=0, shown=ad_state["shown"] + 1)
    if len(gone) == len(bars):          # クリア後
        if AFTER == "same":             # 最悪ケース：クリア後も盤面そっくりの画面が出続ける
            return src.copy()
        img[345:2000] = bg              # 通常：盤面のない画面
        if AFTER == "next":             # 盤面なし画面を3回見せたら次の面（同じ盤面）を出す
            global blank_reads
            blank_reads += 1
            if blank_reads >= 3 and not ad_state["on"]:
                global cleared
                cleared += 1
                gone.clear()
                blank_reads = 0
        return img
    for i in gone:
        for u in bars[i]["path"]:
            x, y = map(int, P(*u))
            cv2.circle(img, (x, y), int(pitch * 0.55), bg, -1)
        for a, b in zip(bars[i]["path"], bars[i]["path"][1:]):
            (xa, ya), (xb, yb) = P(*a), P(*b)
            cv2.circle(img, (int((xa + xb) / 2), int((ya + yb) / 2)), int(pitch * 0.55), bg, -1)
    return img


def bar_free(i):
    (c, r), (dc, dr) = bars[i]["head"], bars[i]["d"]
    c, r = c + dc, r + dr
    while 0 <= c < board["nx"] and 0 <= r < board["ny"]:
        j = occ.get((c, r))
        if j is not None and j != i and j not in gone:
            return False
        c, r = c + dc, r + dr
    return True


def fake_tap(p):
    global manual_wait
    manual_wait = 0
    global misses, taps
    if ad_state["on"]:
        if os.environ.get("AD") == "btn" and abs(p[0] - 1007) < 40 and abs(p[1] - 153) < 40:
            ad_state["on"] = False          # スキップボタンで閉じた
        else:
            print("  !! 広告の中身をタップ", p)
            misses += 1
        return
    taps += 1
    i = bar_at(*p)
    if i is None:
        misses += 1
        print("  !! 空振り", p)
        return
    (c, r), (dc, dr) = bars[i]["head"], bars[i]["d"]
    c, r = c + dc, r + dr
    while 0 <= c < board["nx"] and 0 <= r < board["ny"]:
        j = occ.get((c, r))
        if j is not None and j != i and j not in gone:
            misses += 1
            print("  !! 塞がれた棒を押した", p, "（アニメ中の棒に塞がれていた）" if j in moving else "")
            return
        c, r = c + dc, r + dr
    if i in moving:
        return
    if ANIM:
        moving[i] = ANIM
    else:
        gone.add(i)


GAME = "com.example.arrows/com.unity3d.player.UnityPlayerActivity"
ADC = "com.example.arrows/com.applovin.adview.AppLovinFullscreenActivity"
AD = os.environ.get("AD", "")          # AD=1 でクリア後に広告。戻る2回まではカウントダウン中で無視
STORE = os.environ.get("STORE", "")    # STORE=1 で広告の1回目の戻るがストアに飛ばされる
ad_state = dict(on=False, backs=0, store=False, shown=0, away=0)
AWAY = os.environ.get("AWAY", "")
GREPFAIL = os.environ.get("GREPFAIL", "")  # GREPFAIL=1 で前面画面名が取れない端末を再現      # AWAY=1 でクリア後しばらく Claude アプリが前面（戻るを押したらミス）
backs_total = 0


def fake_adb(*a, **k):
    global backs_total, misses
    cmd = a[-1]
    if "dumpsys" in cmd and GREPFAIL:
        # 実機：grep が何も見つけないと終了コード1 → adb がエラーとして返す
        if not cmd.rstrip().endswith("true"):
            raise kb.AdbError("exit 1")
        return ""
    if "dumpsys" in cmd:
        if AWAY and len(gone) == len(bars) and ad_state["away"] < 6:
            ad_state["away"] += 1
            return "topResumedActivity=ActivityRecord{1 u0 com.anthropic.claude/.MainActivity t7}"
        if ad_state["store"]:
            return "topResumedActivity=ActivityRecord{1 u0 com.android.vending/.AssetBrowserActivity t9}"
        comp = ADC if ad_state["on"] else GAME
        pkg, cls = comp.split("/")
        return f"  topResumedActivity=ActivityRecord{{1 u0 {pkg}/{cls} t5}}"
    if "KEYCODE_BACK" in cmd:
        backs_total += 1
        if AWAY and len(gone) == len(bars) and ad_state["away"] < 6:
            print("  !! 別アプリ使用中に戻るを押した")
            misses += 1
        if ad_state["store"]:
            ad_state["store"] = False
        elif ad_state["on"] and AD == "btn":
            pass                            # 戻るを受け付けない広告
        elif ad_state["on"]:
            ad_state["backs"] += 1
            if STORE and ad_state["backs"] == 1:
                ad_state["store"] = True
            elif ad_state["backs"] >= 3:
                ad_state["on"] = False
        else:
            print("  !! ゲーム画面で戻るを押した")
            misses += 1
        return ""
    if "input tap" in cmd and ad_state["on"]:
        print("  !! 広告中にタップした")
    return ""


kb.adb = fake_adb
kb.screencap, kb.tap = fake_screencap, fake_tap
ab.tap_many = lambda pts, gap: [fake_tap(p) for p in pts]
kb.online_devices = lambda: ["sim"]
kb.time.sleep = ab.time.sleep = lambda s: None
AFTER = os.environ.get("AFTER", "blank")
sys.argv = ["arrow_bot.py", "--start-delay", "0", "--save", ""] + sys.argv[2:]
ab.main()
print(f"結果: タップ{taps}回 / 抜けた{len(gone)}/{len(bars)}本 / ミス{misses}回 / 戻る{backs_total}回 / 広告{ad_state['shown']}回・残り表示中={ad_state['on']}")
sys.exit(0 if misses == 0 else 1)
