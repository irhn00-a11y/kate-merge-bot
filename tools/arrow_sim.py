#!/usr/bin/env python3
"""arrow_bot の実機ループを仮想ゲームで回すテスト（ADB不要）

- 画面取得 → 実スクショから、抜けた棒を背景色で塗りつぶした画像を返す
- タップ   → 押された棒の頭の先に他の棒が残っていたら「ミス」として数える
  使い方: python tools/arrow_sim.py docs/arrow_board.jpg
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import arrow_bot as ab  # noqa: E402
import kate_merge_bot as kb  # noqa: E402

src = cv2.imread(sys.argv[1])
board, _ = ab.parse_board(src)
bars, P, pitch = board["bars"], board["P"], board["pitch"]
bg = tuple(int(v) for v in np.median(src[400:500, 40:1040].reshape(-1, 3), 0))
gone, misses, taps = set(), 0, 0
occ = {u: i for i, b in enumerate(bars) for u in b["path"]}


def bar_at(x, y):
    c, r = round((x - P(0, 0)[0]) / pitch), round((y - P(0, 0)[1]) / pitch)
    i = occ.get((c, r))
    return None if i is None or i in gone else i


def fake_screencap():
    img = src.copy()
    if len(gone) == len(bars):          # クリア後は盤面のない画面
        img[345:2000] = bg
        return img
    for i in gone:
        for u in bars[i]["path"]:
            x, y = map(int, P(*u))
            cv2.circle(img, (x, y), int(pitch * 0.55), bg, -1)
        for a, b in zip(bars[i]["path"], bars[i]["path"][1:]):
            (xa, ya), (xb, yb) = P(*a), P(*b)
            cv2.circle(img, (int((xa + xb) / 2), int((ya + yb) / 2)), int(pitch * 0.55), bg, -1)
    return img


def fake_tap(p):
    global misses, taps
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
            print("  !! 塞がれた棒を押した", p)
            return
        c, r = c + dc, r + dr
    gone.add(i)


kb.screencap, kb.tap = fake_screencap, fake_tap
ab.tap_many = lambda pts, gap: [fake_tap(p) for p in pts]
kb.online_devices = lambda: ["sim"]
kb.time.sleep = ab.time.sleep = lambda s: None
sys.argv = ["arrow_bot.py", "--levels", "1", "--start-delay", "0", "--save", ""] + sys.argv[2:]
ab.main()
print(f"結果: タップ{taps}回 / 抜けた{len(gone)}/{len(bars)}本 / ミス{misses}回")
sys.exit(0 if misses == 0 and len(gone) == len(bars) else 1)
