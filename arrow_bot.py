#!/usr/bin/env python3
"""
矢印パズル（棒を矢印の向きに抜いて全部逃がすゲーム）自動解答bot

  screencap → グリッド上の棒を抽出 → 矢印の頭を判定 → 貪欲法で解く → input tap

ルール: 棒は矢印の頭の向きへ抜ける。その直線上に他の棒があると抜けない。
        抜けた棒は空きを増やすだけで他を塞がないので、
        「今抜ける棒を抜く」を繰り返すだけで解ける盤面は必ず解ける（探索不要）。

使い方:
  python arrow_bot.py --analyze shot.jpg    # 画像1枚を解いて arrow_solution.png を出す（ADB不要）
  python arrow_bot.py --dry-run             # 実機を読んで解答画像を保存するだけ。タップしない
  python arrow_bot.py --step                # 1本タップするたびに読み直す（慎重モード）
  python arrow_bot.py                       # 本番（盤面が消えたら次の面を待つ。Ctrl+Cで停止）

adb接続・画面取得は kate_merge_bot.py のものを使う（同じフォルダに置くこと）。
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kate_merge_bot as kb  # noqa: E402  adb / screencap / auto_connect / is_termux を流用

# ===== 1080x2340 基準の値（解像度が違えば高さ比で換算） =====
REF_H = 2340
SEARCH_Y = (345, 2000)   # 盤面を探す縦範囲（上のヘッダ線より下、下のボタンより上）
DARK = 120               # これより暗い画素を「線」とみなす
REF_PITCH = 43.7         # 判定オフセットの基準にしたマス幅
TAP_WAIT = 0.12          # 同じ波の中でのタップ間隔（v2で0.35→0.12）
WAVE_WAIT = 0.4          # 波と波の間（前の棒が抜けきるのを待つ。v2で0.8→0.4）


# ---------------- 盤面解析 ----------------
def _runs(on):
    out, s = [], None
    for i, v in enumerate(on):
        if v and s is None:
            s = i
        if not v and s is not None:
            out.append((s, i - 1))
            s = None
    if s is not None:
        out.append((s, len(on) - 1))
    return out


def _fit_axis(B, axis, lo, hi, line_w):
    """線の中心が並ぶ等間隔グリッドを当てはめる。戻り値 (原点, ピッチ, 個数) """
    prof = B.sum(axis)
    thr = max(5, 0.25 * np.percentile(prof[prof > 0], 90)) if (prof > 0).any() else 5
    cs = [(a + b) / 2 for a, b in _runs(prof > thr) if line_w * 0.5 <= b - a + 1 <= line_w * 1.8]
    if len(cs) < 3:
        return None
    cs = np.array(cs)
    # ピッチ：線の中心が最もよく揃う周期を探す（線幅の2〜6倍の範囲。半分・倍の周期は範囲外）
    ps = np.arange(line_w * 2, line_w * 6, 0.05)
    score = [abs(np.exp(2j * np.pi * cs / p).sum()) for p in ps]
    p = ps[int(np.argmax(score))]
    phase = np.angle(np.exp(2j * np.pi * cs / p).sum()) / (2 * np.pi) * p
    k = np.round((cs - phase) / p)
    # 線の中心をグリッド番号に対して最小二乗フィット（ズレていた点は除外）
    ok = np.abs(cs - phase - k * p) < line_w * 0.6
    A = np.vstack([np.ones(ok.sum()), k[ok]]).T
    (c0, p), *_ = np.linalg.lstsq(A, cs[ok], rcond=None)
    # 外周は先端の突き出し（<半マス）を考慮して点の範囲から決める
    idx = np.nonzero(prof > 0)[0]
    first = int(np.ceil((idx[0] - c0) / p - 0.05))
    last = int(np.floor((idx[-1] - c0) / p + 0.05))
    return lo + c0 + first * p, p, last - first + 1


def parse_board(img, grid=None):
    """盤面を読む。戻り値 (dict(bars, nx, ny, P, grid…), None) か、読めなければ (None, 理由)
    grid を渡すとグリッド推定を省いてそれを使う（棒が減ると推定が不安定になるため、面の最初に読んだものを固定）"""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    s = H / REF_H
    y_lo, y_hi = int(SEARCH_Y[0] * s), int(SEARCH_Y[1] * s)
    B = np.zeros_like(g, bool)
    B[y_lo:y_hi] = g[y_lo:y_hi] < DARK
    if B.sum() < 300 * s * s:
        return None, "盤面なし"
    if grid is None:
        if B.sum() < 2000 * s * s:
            return None, "盤面なし"
        ys, xs = np.nonzero(B)
        sub = B[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        # 線幅の目安：短い黒ランの中央値
        rl = [b - a + 1 for row in sub[::7] for a, b in _runs(row)]
        line_w = float(np.median(rl)) if rl else 12
        fx = _fit_axis(sub, 0, xs.min(), xs.max(), line_w)
        fy = _fit_axis(sub, 1, ys.min(), ys.max(), line_w)
        if not fx or not fy:
            return None, "グリッド検出失敗"
        grid = fx + fy
    (x0, px, nx, y0, py, ny) = grid
    if abs(px - py) > 0.1 * px or nx < 2 or ny < 2:
        return None, f"グリッドが不自然 px={px:.1f} py={py:.1f}"
    P = lambda c, r: (x0 + c * px, y0 + r * py)  # noqa: E731
    k = px / REF_PITCH

    def dark(x, y, r=3):
        x, y = int(round(x)), int(round(y))
        if not (r <= x < W - r and r <= y < H - r):
            return False
        return B[y - r:y + r + 1, x - r:x + r + 1].mean() > 0.5

    nodes = {(c, r) for c in range(nx) for r in range(ny) if dark(*P(c, r))}
    adj = {u: set() for u in nodes}
    for (c, r) in nodes:
        for dc, dr in ((1, 0), (0, 1)):
            v = (c + dc, r + dr)
            if v in nodes:
                (xa, ya), (xb, yb) = P(c, r), P(*v)
                if dark((xa + xb) / 2, (ya + yb) / 2):
                    adj[(c, r)].add(v)
                    adj[v].add((c, r))

    def head_score(e, d):
        # 矢印の頭：端点から先に突き出た先端＋左右の羽
        x, y = P(*e)
        dc, dr = d
        sc = int(dark(x + dc * 15 * k, y + dr * 15 * k, 2))
        for sg in (1, -1):
            sc += int(dark(x - dc * 2 * k + sg * dr * 14 * k, y - dr * 2 * k + sg * dc * 14 * k, 2))
        return sc

    seen, bars, problems, noise = set(), [], [], []
    for u0 in nodes:
        if u0 in seen:
            continue
        comp, st = [], [u0]
        while st:
            u = st.pop()
            if u in seen:
                continue
            seen.add(u)
            comp.append(u)
            st += adj[u]
        ends = [u for u in comp if len(adj[u]) == 1]
        if len(comp) == 1:
            noise.append(comp[0])   # 1点だけ＝棒ではない（通話の吹き出し等のオーバーレイ、ゴミ）
            continue
        if len(ends) != 2 or any(len(adj[u]) > 2 for u in comp):
            problems.append((comp, "分岐/交差"))
            continue
        sc = []
        for e in ends:
            nb = next(iter(adj[e]))
            d = (e[0] - nb[0], e[1] - nb[1])
            sc.append((head_score(e, d), e, d))
        sc.sort(reverse=True)
        if sc[0][0] < 2 or sc[1][0] >= 2:
            problems.append((comp, f"頭が曖昧 {sc[0][0]}/{sc[1][0]}"))
            continue
        _, head, d = sc[0]
        tail = sc[1][1]
        path, prev = [tail], None
        while path[-1] != head:
            u = path[-1]
            nxt = [v for v in adj[u] if v != prev][0]
            prev, _ = u, path.append(nxt)
        bars.append(dict(path=path, head=head, d=d))
    return dict(bars=bars, problems=problems, noise=noise, nx=nx, ny=ny, P=P, pitch=px, grid=grid), None


def solve(board):
    """貪欲法。戻り値: 波のリスト（同じ波の棒は互いに独立）と、抜けない棒"""
    bars, nx, ny = board["bars"], board["nx"], board["ny"]
    occ = {u: i for i, b in enumerate(bars) for u in b["path"]}
    alive = set(range(len(bars)))

    def free(i):
        (c, r), (dc, dr) = bars[i]["head"], bars[i]["d"]
        c, r = c + dc, r + dr
        while 0 <= c < nx and 0 <= r < ny:
            j = occ.get((c, r))
            if j is not None and j in alive and j != i:   # 自分の体は無視（要実機確認）
                return False
            c, r = c + dc, r + dr
        return True

    waves = []
    while alive:
        w = [i for i in sorted(alive) if free(i)]
        if not w:
            break
        waves.append(w)
        alive -= set(w)
    return waves, sorted(alive)


def tap_point(board, i):
    p = board["bars"][i]["path"]
    return tuple(int(v) for v in board["P"](*p[len(p) // 2]))


def annotate(img, board, waves, stuck):
    out = img.copy()
    P = board["P"]
    n = 0
    for w in waves:
        for i in w:
            n += 1
            x, y = tap_point(board, i)
            cv2.circle(out, (x, y), 17, (40, 120, 240), -1)
            cv2.putText(out, str(n), (x - (14 if n >= 10 else 8), y + 7),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    for b in board["bars"]:
        cv2.circle(out, tuple(int(v) for v in P(*b["head"])), 9, (60, 200, 60), 3)
    for i in stuck:
        for u in board["bars"][i]["path"]:
            cv2.circle(out, tuple(int(v) for v in P(*u)), 6, (0, 0, 255), -1)
    for u in board["noise"]:
        cv2.circle(out, tuple(int(v) for v in P(*u)), 8, (160, 160, 160), 2)
    for comp, _ in board["problems"]:
        for u in comp:
            cv2.circle(out, tuple(int(v) for v in P(*u)), 6, (255, 0, 255), -1)
    return out


def analyze(img, grid=None):
    board, err = parse_board(img, grid)
    if err:
        return None, None, None, err
    waves, stuck = solve(board)
    return board, waves, stuck, None


def report(board, waves, stuck):
    n = sum(map(len, waves))
    print(f"グリッド {board['nx']}x{board['ny']}  マス幅 {board['pitch']:.1f}px  棒 {len(board['bars'])}本")
    print(f"解答 {n}手 / {len(waves)}波  抜けない棒 {len(stuck)}  読み取り不良 {len(board['problems'])}")
    if board["noise"]:
        print(f"  無視した点（棒ではない）: {board['noise']}")
    for comp, why in board["problems"]:
        print("  不良:", why, sorted(comp)[:3], "…")



# ---------------- 広告 ----------------
# 前面のActivity名で判定する（画像認識より確実）。ゲーム画面と違う Activity が前に出ていたら広告とみなす
AD_HINTS = ("adactivity", "applovin", "unity3d", "ironsource", "vungle", "liftoff", "mbridge",
            "mintegral", "chartboost", "fyber", "inneractive", "inmobi", "bytedance", "pangle",
            "facebook.ads", "audiencenetwork", "moloco", "bigo", "yandex.mobile.ads", "adcolony",
            "tapjoy", "digitalturbine", "smaato", "startapp", "appodeal", "admob", "interstitial",
            "fullscreen", ".ads.", "ads.", "rewarded")
# 広告から飛ばされがちな先（ストア・ブラウザ）：戻るで帰ってよい
OUTSIDE_OK = ("com.android.vending", "com.android.chrome", "com.sec.android.app.sbrowser",
              "org.mozilla", "com.google.android.googlequicksearchbox")
# ユーザー自身の操作（Termuxやホームに戻った等）：何もしない
HANDS_OFF = ("com.termux", "launcher", "com.android.systemui", "com.android.settings",
             "incallui", "dialer", "telecom", "com.android.phone")


def top_activity():
    """前面のActivity。'パッケージ/クラス' の文字列。取れなければ None"""
    import re
    for cmd in ("dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity'",
                "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"):
        try:
            out = kb.adb("shell", cmd, timeout=8)
        except kb.AdbError:
            raise
        except Exception:
            continue
        m = re.search(r"u\d+ ([\w.]+)/([\w.$]+)", out)
        if m:
            pkg, cls = m.groups()
            return f"{pkg}/{pkg + cls if cls.startswith('.') else cls}"
    return None


def ad_kind(comp, game, recent_ad=False):
    """'game' / 'ad'(閉じにいく) / 'away'(ユーザーが別アプリを使用中：触らない) / 'unknown'(記録だけ)
    recent_ad: 直前まで広告が出ていた（ストア・ブラウザはその時だけ広告の飛び先とみなす）"""
    if comp is None or comp == game:
        return "game"
    low = comp.lower()
    if any(h in low for h in HANDS_OFF):
        return "away"
    if any(h in low for h in AD_HINTS):
        return "ad"
    if low.startswith(OUTSIDE_OK) and recent_ad:
        return "ad"          # 広告から飛ばされたストア/ブラウザ → 戻るで帰る
    if game and comp.split("/")[0] != game.split("/")[0]:
        return "away"        # 自分で別アプリ（Claude等）を開いた → 何もしない
    return "unknown"         # ゲーム内の別画面（クリア画面等かも）→ 記録だけして触らない


def find_close_button(img, exclude=(), ref=None):
    """広告の閉じる/スキップボタン候補：画面上部の左右の隅にある、中に記号がある丸ボタン。
    戻り値 (x, y) か None。2026-11-05 のAdMob動画広告（右上の ▷| ）で検出を確認
    exclude: 押さない位置（押しても閉じなかった所）
    ref: ゲーム画面のスクショ。同じ位置に見た目までそっくりの丸がある＝通話の吹き出し等のオーバーレイなので押さない"""
    H, W = img.shape[:2]
    s = W / 1080
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    best = None
    gr = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY) if ref is not None and ref.shape == img.shape else None
    for x0, x1 in ((0, int(W * .25)), (int(W * .75), W)):
        roi = cv2.GaussianBlur(g[0:int(H * .15), x0:x1], (5, 5), 0)
        cs = cv2.HoughCircles(roi, cv2.HOUGH_GRADIENT, dp=1.2, minDist=30 * s, param1=60, param2=22,
                              minRadius=int(18 * s), maxRadius=int(60 * s))
        if cs is None:
            continue
        for cx, cy, r in cs[0]:
            m = np.zeros_like(roi, np.uint8)
            cv2.circle(m, (int(cx), int(cy)), int(r * .85), 255, -1)
            ring = np.zeros_like(roi, np.uint8)
            cv2.circle(ring, (int(cx), int(cy)), int(r * 1.4), 255, -1)
            ring[m > 0] = 0
            inside, outside = roi[m > 0], roi[ring > 0]
            if inside.size == 0 or outside.size == 0:
                continue
            icon = np.percentile(inside, 95) - np.percentile(inside, 50)   # 円の中に記号がある
            edge = abs(float(np.median(inside)) - float(np.median(outside)))  # 円と外側の色が違う
            sc = min(icon, 120) + min(edge, 60)
            if any(abs(cx + x0 - ex) < 45 * s and abs(cy - ey) < 45 * s for ex, ey in exclude):
                continue
            if gr is not None:
                X, Y, R = int(cx + x0), int(cy), max(4, int(r * 0.7))   # 丸の内側だけ比べる（外側は背景が違う）
                a = g[max(0, Y - R):Y + R, max(0, X - R):X + R].astype(int)
                b = gr[max(0, Y - R):Y + R, max(0, X - R):X + R].astype(int)
                if a.size and (np.abs(a - b) < 12).mean() > 0.6:
                    continue     # 6割以上の画素がゲーム画面と同じ＝オーバーレイ（丸が吹き出しからはみ出しても判定できる）
            if icon > 40 and edge > 8 and (best is None or sc > best[0]):
                best = (sc, int(cx + x0), int(cy))
    return best[1:] if best else None


def back():
    kb.adb("shell", "input keyevent KEYCODE_BACK")


def ad_sample(args, tag, comp):
    """広告の調査用：スクショと記録を残す（広告いなしbotの下調べを兼ねる）"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    d = os.path.expanduser(args.ad_dir)
    os.makedirs(d, exist_ok=True)
    try:
        cv2.imwrite(os.path.join(d, f"{ts}_{tag}.png"), kb.screencap())
    except kb.AdbError:
        raise
    except Exception:
        pass
    with open(os.path.expanduser(args.ad_log), "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%F %T')},{tag},{comp}\n")


# ---------------- 実機ループ ----------------
def tap_many(points, gap):
    """1波ぶんのタップを1回の adb shell にまとめる（1タップごとのadb往復を省く）"""
    if len(points) == 1:
        return kb.tap(points[0])
    cmd = f"; sleep {gap:.2f}; ".join(f"input tap {x} {y}" for x, y in points)
    kb.adb("shell", cmd, timeout=10 + len(points) * (gap + 1))


def save(path, img):
    if path:
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        cv2.imwrite(path, img)


def _paths(board):
    return {tuple(b["path"]) for b in board["bars"]}


def run(args):
    """状態:
    seek … 新しい面を待つ。「読み取り不良0・全部解ける・2回続けて同じ盤面」を満たしたら開始
    play … その面を解く。読み直した盤面は「さっき残っていた棒の部分集合」でなければ異常とみなして押さない
    面クリア後は、一度盤面が消える（またはクリア画面になる）のを確認してから次の面を待つ"""
    if not kb.online_devices() and not kb.auto_connect():
        print("adbにつながらない（ワイヤレスデバッグONを確認）")
        return
    kb.SERIAL = kb.SERIAL or kb.online_devices()[0]
    if args.start_delay:
        print(f"{args.start_delay}秒後に開始。今のうちにゲーム画面へ")
        time.sleep(args.start_delay)
    stop_file = os.path.expanduser(args.stop_file)
    if os.path.exists(stop_file):
        os.remove(stop_file)
    print(f"開始。止めるには Ctrl+C か `touch {args.stop_file}`")
    levels = taps = waiting = bad = 0
    state, grid, alive, last_seen = "seek", None, set(), None
    need_gap = False     # クリア直後：盤面が一度消えるまで新しい面とみなさない
    t_level = None
    game = None          # ゲーム画面の Activity（最初に盤面を解き始めた時に記録）
    ad = None            # 表示中の広告 dict(comp, t0, backs, last_back, sampled)
    finish_at = None     # 指定面数をクリアした時刻。広告が出たら閉じてから止める
    last_ad = 0          # 最後に広告を見た時刻（ストア等を広告の飛び先とみなす判定用）
    game_ref = None      # ゲーム画面のスクショ（通話の吹き出し等のオーバーレイを広告ボタンと区別する）
    while True:
        if os.path.exists(stop_file):
            print("停止ファイルを検出")
            break
        if state == "seek" and game and not args.no_ad:
            comp = top_activity()
            kind = ad_kind(comp, game, recent_ad=time.time() - last_ad < 30)
            if kind != "game":
                now = time.time()
                if ad is None or ad["comp"] != comp:
                    ad = dict(comp=comp, t0=now, backs=0, taps=0, last_act=0, sampled=False, kind=kind, n=0,
                              tried={}, dead=[])
                    print(f"広告/別画面: {comp}（{kind}）")
                if kind == "away":
                    # 自分で別アプリを使っている間は何もしない（戻すと邪魔になる）
                    if now - ad["t0"] > args.away_stop:
                        print(f"{args.away_stop:.0f}秒ゲームに戻らないので停止")
                        break
                    time.sleep(1.0)
                    continue
                if not ad["sampled"] and now - ad["t0"] > 1.0:
                    ad_sample(args, kind, comp)
                    ad["sampled"] = True
                if kind == "ad":
                    last_ad = now
                    if now - ad["last_act"] >= args.ad_back:
                        # 閉じる/スキップの丸ボタンがあれば押す。なければ戻る。
                        # 同じ所を押しても閉じない時のため、ボタンと戻るを交互に試す
                        btn = find_close_button(kb.screencap(), ad["dead"], game_ref) if ad["n"] % 2 == 0 else None
                        if btn:
                            kb.tap(btn)
                            ad["taps"] += 1
                            hit = ad["tried"].setdefault(btn, 0) + 1
                            ad["tried"][btn] = hit
                            print(f"  閉じるボタンらしき所をタップ {btn}")
                            if hit >= 2:
                                ad["dead"].append(btn)   # 2回押しても閉じない所は以後押さない
                        else:
                            back()
                            ad["backs"] += 1
                        ad["n"] += 1
                        ad["last_act"] = now
                if now - ad["t0"] > args.ad_timeout:
                    ad_sample(args, "timeout", comp)
                    print(f"{args.ad_timeout:.0f}秒閉じられないので停止（スクショを {args.ad_dir} に保存）")
                    break
                waiting = 0
                time.sleep(0.5)
                continue
            if ad:
                if ad["kind"] == "away":
                    print("ゲームに戻ってきた")
                else:
                    print(f"広告を閉じた（{time.time() - ad['t0']:.1f}秒 / ボタン{ad['taps']}回 / 戻る{ad['backs']}回）")
                with open(os.path.expanduser(args.ad_log), "a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%F %T')},closed_{ad['kind']},{ad['comp']},{time.time() - ad['t0']:.1f}s,btn{ad['taps']},back{ad['backs']}\n")
                ad = None
                if finish_at:
                    break
            if finish_at and time.time() - finish_at > args.ad_grace:
                break        # 指定面数クリア後、広告が出なかった
        img = kb.screencap()
        board, waves, stuck, err = analyze(img, grid if state == "play" else None)
        has = not err and board["bars"]

        if state == "play":
            if not has or not _paths(board):
                # 残りを全部押した後に盤面が消えた → クリア
                print(f"== クリア（{levels + 1}面目 / {time.time() - t_level:.1f}秒） ==" if not alive
                      else "== 盤面が消えた（途中）→ 新しい面を待つ ==")
                levels += 1 if not alive else 0
                state, grid, need_gap = "seek", None, False
                if args.levels and levels >= args.levels:
                    if not game:
                        break
                    finish_at = time.time()
                continue
            if not _paths(board) <= alive or board["problems"]:
                # 想定外の棒が増えた＝クリア画面や次の面、または読み違い → 押さない
                print("盤面が想定と違う → 押さずに様子見")
                if not alive:
                    levels += 1
                    print(f"== クリア（{levels}面目 / {time.time() - t_level:.1f}秒） ==")
                    if args.levels and levels >= args.levels:
                        if not game:
                            break
                        finish_at = time.time()
                    need_gap = True
                state, grid, last_seen = "seek", None, None
                time.sleep(args.poll)
                continue
        else:  # seek
            ok = has and not board["problems"] and not stuck and waves
            if not ok:
                if has and board["problems"]:
                    bad += 1
                    save(args.save, annotate(img, board, waves, stuck))
                    report(board, waves, stuck)
                    print(f"読み取り不良あり → タップしない（{bad}回目）。画像: {args.save}")
                    if bad >= args.max_bad:
                        print(f"{args.max_bad}回続けて読めないので停止")
                        break
                if not has:
                    need_gap = False
                if finish_at:
                    time.sleep(0.5)
                    continue
                waiting += 1
                if waiting == 1:
                    print(f"盤面待ち（{err or '解ける盤面なし'}）。次の面を開いて")
                if waiting * args.poll > args.idle_stop:
                    print(f"{args.idle_stop}秒盤面が出ないので停止")
                    break
                last_seen = None
                time.sleep(args.poll)
                continue
            if need_gap or finish_at:
                if finish_at:
                    time.sleep(0.5)
                    continue
                waiting += 1
                if waiting == 1:
                    print("クリア後の画面待ち（盤面が一度消えるまで押さない）")
                if waiting * args.poll > args.idle_stop:
                    print(f"{args.idle_stop}秒たっても画面が変わらないので停止")
                    break
                time.sleep(args.poll)
                continue
            if _paths(board) != last_seen:      # アニメ中の誤読を避けるため2回同じなら開始
                last_seen = _paths(board)
                time.sleep(0.3)
                continue
            waiting = bad = 0
            state, grid, alive, t_level = "play", board["grid"], _paths(board), time.time()
            if game is None and not args.no_ad:
                game = top_activity()
                print(f"ゲーム画面: {game}")
            if not args.no_ad:
                game_ref = img      # 広告中に「ゲーム画面にもある丸」を除外するための見本
            report(board, waves, stuck)

        save(args.save, annotate(img, board, waves, stuck))
        if not waves:
            report(board, waves, stuck)
            print("抜ける棒がない（読み違いか、ルール解釈違い）→ 停止")
            break
        plan = [waves[0][:1]] if args.step else waves
        if args.dry_run:
            print(f"dry-run: 解答画像を保存 → {args.save}")
            break
        print(f"棒{len(board['bars'])}本 → {sum(map(len, plan))}手実行")
        for wi, w in enumerate(plan):
            tap_many([tap_point(board, i) for i in w], args.tap_wait)
            taps += len(w)
            if wi < len(plan) - 1:
                time.sleep(args.wave_wait)
        alive = _paths(board) - {tuple(board["bars"][i]["path"]) for w in plan for i in w}
        time.sleep(args.wave_wait)   # 抜けきってから読み直す（残っていれば続きを解く）
    print(f"合計 {taps}タップ / {levels}面")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyze", metavar="IMAGE", help="画像を解いて arrow_solution.png を出力")
    ap.add_argument("--dry-run", action="store_true", help="実機を読んで解答画像を保存するだけ")
    ap.add_argument("--step", action="store_true", help="1タップごとに読み直す（慎重モード）")
    ap.add_argument("--levels", type=int, default=1, help="この面数クリアしたら停止（0=無制限。次の面は自分で開く）")
    ap.add_argument("--tap-wait", type=float, default=TAP_WAIT, help="同じ波の中のタップ間隔（秒）")
    ap.add_argument("--wave-wait", type=float, default=WAVE_WAIT, help="波と波の間の待ち（秒）")
    ap.add_argument("--no-ad", action="store_true", help="広告処理をしない")
    ap.add_argument("--ad-back", type=float, default=2.0, help="広告中に閉じる操作をする間隔（秒）")
    ap.add_argument("--away-stop", type=float, default=600, help="別アプリを開いたままこの秒数たったら停止")
    ap.add_argument("--ad-timeout", type=float, default=90, help="広告がこの秒数閉じなければ停止")
    ap.add_argument("--ad-grace", type=float, default=5, help="最終面クリア後、広告が出るのを待つ秒数")
    ap.add_argument("--ad-dir", default="~/storage/shared/Pictures/arrow_ads" if kb.is_termux() else "arrow_ads", help="広告スクショの保存先")
    ap.add_argument("--ad-log", default="~/arrow_ad_log.csv", help="広告の記録")
    ap.add_argument("--max-bad", type=int, default=5, help="読み取り不良がこの回数続いたら停止")
    ap.add_argument("--poll", type=float, default=1.0, help="盤面待ちの確認間隔（秒）")
    ap.add_argument("--idle-stop", type=float, default=120, help="盤面がこの秒数出なければ停止")
    ap.add_argument("--start-delay", type=float, default=5, help="開始前の待ち（ゲームへ切替える時間）")
    ap.add_argument("--serial", help="adbの接続先（例 127.0.0.1:37123）")
    ap.add_argument("--stop-file", default="~/arrow_stop", help="このファイルを作ると停止")
    ap.add_argument("--save", default="~/storage/shared/Pictures/arrow_bot_latest.png"
                    if kb.is_termux() else "arrow_bot_latest.png", help="毎回の解答画像の保存先")
    args = ap.parse_args()
    kb.SERIAL = args.serial
    if args.analyze:
        img = cv2.imread(args.analyze)
        if img is None:
            sys.exit(f"画像を開けない: {args.analyze}")
        board, waves, stuck, err = analyze(img)
        if err:
            sys.exit(err)
        report(board, waves, stuck)
        cv2.imwrite("arrow_solution.png", annotate(img, board, waves, stuck))
        print("→ arrow_solution.png")
        return
    try:
        run(args)
    except KeyboardInterrupt:
        print("\n停止")
    except kb.AdbError as e:
        print(f"adbが切れた: {e}（python kate_merge_bot.py --connect で再接続して再実行）")


if __name__ == "__main__":
    main()
