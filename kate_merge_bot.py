#!/usr/bin/env python3
"""
ケイトの冒険（マージパズル）自動マージbot

  PC ──ADB──> Android
   ├ screencap で盤面取得
   ├ OpenCVで 7x9 マスを分類（空き/段ボール/ガラス瓶/アイテム）
   ├ 同じアイテムをペアにして input swipe で合体
   └ 認識結果を別ウィンドウにオーバーレイ表示（ロマン枠）

使い方:
  python kate_merge_bot.py --analyze shot.jpg   # 画像1枚だけ解析して annotated.png を出す（ADB不要）
  python kate_merge_bot.py --dry-run            # 実機の画面を読むだけ。スワイプしない
  python kate_merge_bot.py                      # 自動マージ開始（Ctrl+Cで停止）
  python kate_merge_bot.py --produce 5,3 1,3    # 合体が尽きたら生産機を順番にタップして補充

前提: 1080x2340 縦画面で調整済み。解像度が違う場合は BOARD を比率で自動換算。
"""
import argparse
import os
import subprocess
import sys
import time

import cv2
import numpy as np

# ===== 盤面定義（1080x2340 基準の内側ピクセル範囲） =====
REF_W, REF_H = 1080, 2340
BOARD = dict(x0=70, y0=752, x1=1008, y1=1970)
COLS, ROWS = 7, 9

# ===== 認識しきい値（実機で合わなければここを調整） =====
SAME_THRESHOLD = 0.80     # この類似度以上なら同じアイテムとみなす
ORDER_THRESHOLD = 0.60    # 注文アイコンとのテンプレ一致度がこれ以上 かつ…
ORDER_MARGIN = 0.12       # …その注文の最高一致から この差以内なら保護（マージしない）
ORDER_BAND = (380, 720)   # 注文パネルを探す縦範囲（1080x2340基準）
ORDER_MIN_X = 230         # これより左はスパナボタン等なので除外
SWIPE_MS = 150            # ドラッグ時間
WAIT_AFTER_MERGE = 0.35   # 1手ごとの待ち
BATCH = 8                 # 1回の盤面読み取りで実行する最大手数（重ならないペアをまとめて実行）
PRODUCE_TIMEOUT = 2.5     # 生産タップ後、アイテムが着地するのを最大何秒見張るか
PRODUCE_POLL = 0.35       # 見張る間隔
CHANGE_DIFF = 18          # 空きマスの画素がこれ以上変わったら「何か置かれた」とみなす

EMPTY, BOX, JAR, ITEM = "empty", "box", "jar", "item"


# ---------------- ADB ----------------
SERIAL = None   # --serial で指定（Termux自己接続なら 127.0.0.1:ポート）


def adb(*args, binary=False):
    cmd = ["adb"] + (["-s", SERIAL] if SERIAL else []) + list(args)
    out = subprocess.run(cmd, capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode(errors="ignore")


_RAW_OK = True


def screencap():
    """非圧縮のraw形式で取得（PNG圧縮を省くので速い）。失敗したらPNGに切替"""
    global _RAW_OK
    if _RAW_OK:
        try:
            raw = adb("exec-out", "screencap", binary=True)
            w, h = np.frombuffer(raw[:8], "<u4")
            hdr = len(raw) - int(w) * int(h) * 4
            if hdr in (12, 16):
                px = np.frombuffer(raw, np.uint8, offset=hdr).reshape(int(h), int(w), 4)
                return cv2.cvtColor(px, cv2.COLOR_RGBA2BGR)
        except Exception:
            pass
        _RAW_OK = False
        print("raw取得に失敗 → PNG取得に切替")
    raw = adb("exec-out", "screencap", "-p", binary=True)
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("screencap失敗。adb devices で接続を確認して")
    return img


def swipe(p, q, ms=SWIPE_MS):
    adb("shell", "input", "swipe", str(p[0]), str(p[1]), str(q[0]), str(q[1]), str(ms))


def tap(p):
    adb("shell", "input", "tap", str(p[0]), str(p[1]))


# ---------------- 盤面解析 ----------------
def board_rect(img):
    h, w = img.shape[:2]
    sx, sy = w / REF_W, h / REF_H
    return (int(BOARD["x0"] * sx), int(BOARD["y0"] * sy),
            int(BOARD["x1"] * sx), int(BOARD["y1"] * sy))


def cells(img):
    x0, y0, x1, y1 = board_rect(img)
    cw, ch = (x1 - x0) / COLS, (y1 - y0) / ROWS
    for r in range(ROWS):
        for c in range(COLS):
            a, b = int(x0 + c * cw), int(y0 + r * ch)
            e, f = int(x0 + (c + 1) * cw), int(y0 + (r + 1) * ch)
            yield c, r, img[b:f, a:e], ((a + e) // 2, (b + f) // 2)


def board_visible(img):
    """盤面の外枠（ティール）が見えているか。ゲーム以外の画面で誤スワイプしない安全装置"""
    x0, y0, x1, y1 = board_rect(img)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    strips = [hsv[y0 + 2:y1 - 2, x0:x0 + 4], hsv[y0 + 2:y1 - 2, x1 - 4:x1]]
    ratios = [((s[..., 0] >= 68) & (s[..., 0] <= 90) & (s[..., 2] > 170)).mean() for s in strips]
    # V>170: ポップアップで画面が暗転していたら不可にする
    return min(ratios) > 0.5


def classify(cell):
    hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
    h, w = hsv.shape[:2]
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    inner = hsv[int(h * .15):int(h * .85), int(w * .15):int(w * .85)]
    # 背景ティール (H≈75-82, S低め)
    teal = ((inner[..., 0] >= 70) & (inner[..., 0] <= 88) & (inner[..., 1] < 120)).mean()
    # 段ボール（茶色 H≈10-22, S中〜高）
    brown = ((H >= 8) & (H <= 22) & (S > 90) & (V > 120)).mean()
    # 瓶の青いフタ（上部20%に H≈95-110 の高彩度）
    top = hsv[:int(h * .25), int(w * .2):int(w * .8)]
    lid = ((top[..., 0] >= 92) & (top[..., 0] <= 112) & (top[..., 1] > 120)).mean()
    if teal > 0.82:
        return EMPTY
    if brown > 0.45:
        return BOX
    if lid > 0.18:
        return JAR
    return ITEM


def feature(cell):
    """背景ティールを除いた中央部の色ヒスト＋形状"""
    h, w = cell.shape[:2]
    c = cell[int(h * .1):int(h * .9), int(w * .1):int(w * .9)]
    hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
    mask = ~((hsv[..., 0] >= 70) & (hsv[..., 0] <= 88) & (hsv[..., 1] < 120))
    mask = mask.astype(np.uint8) * 255
    hist = cv2.calcHist([hsv], [0, 1], mask, [30, 16], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    shape = cv2.resize(mask, (24, 24)).astype(np.float32) / 255
    return hist.flatten(), shape.flatten()


_TMPL_CACHE = {}    # 注文アイコン → テンプレ
_SCORE_CACHE = {}   # (注文, マス画像) → 一致度。盤面の大半は毎手変わらないので再利用


def is_cream(hsv):
    """注文パネルのクリーム色（H≈28）。白っぽいアイテム（小麦粉など）はHが違うので残る"""
    return (hsv[..., 0] >= 18) & (hsv[..., 0] <= 38) & (hsv[..., 1] < 60) & (hsv[..., 2] > 215)


def read_orders(img):
    """キャラ下のクリーム色パネルから注文アイコンを切り出す → [(bbox, feature)]"""
    h, w = img.shape[:2]
    sx, sy = w / REF_W, h / REF_H
    yb0, yb1 = int(ORDER_BAND[0] * sy), int(ORDER_BAND[1] * sy)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    cream = (is_cream(hsv)).astype(np.uint8)[yb0:yb1]
    n, _, st, _ = cv2.connectedComponentsWithStats(cream)
    orders = []
    for i in range(1, n):
        x, y, pw, ph, _ = st[i]
        if pw < 150 * sx or ph < 70 * sy or x < ORDER_MIN_X * sx:
            continue
        y += yb0
        roi = img[y:y + ph, x:x + pw]
        r = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        obj = (~is_cream(r)).astype(np.uint8)
        obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        n2, lab, s2, _ = cv2.connectedComponentsWithStats(obj)
        for k in range(1, n2):
            ox, oy, ow, oh, oa = s2[k]
            # 枠の切れ端やノイズを除外し、アイコンらしい塊だけ
            if oa < 1500 * sx * sy or not (40 * sx < ow < 160 * sx) or not (40 * sy < oh < 160 * sy):
                continue
            m = (lab[oy:oy + oh, ox:ox + ow] == k).astype(np.uint8) * 255
            icon = roi[oy:oy + oh, ox:ox + ow]
            key = hash(cv2.resize(icon, (16, 16)).tobytes())
            if key not in _TMPL_CACHE:
                _TMPL_CACHE[key] = order_templates(icon, m)
            orders.append(((x + ox, y + oy, ow, oh), _TMPL_CACHE[key], key))
    return orders


MATCH_SCALE = 0.5   # 注文照合は半分の解像度で行う（速度4倍）


def order_templates(icon, mask, scales=np.linspace(1.0, 1.9, 7)):
    """注文アイコンを盤面サイズ相当まで拡大した (テンプレ, マスク) の一覧"""
    out = []
    for s in scales * MATCH_SCALE:
        t = cv2.resize(icon, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        m = cv2.resize(mask, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST)
        out.append((t, m))
    return out


def order_score(cell, templates):
    """マスク付きテンプレートマッチ（背景色の違いを無視して形と色で比較）"""
    best = -1.0
    for t, m in templates:
        if t.shape[0] >= cell.shape[0] or t.shape[1] >= cell.shape[1]:
            break
        r = cv2.matchTemplate(cell, t, cv2.TM_CCOEFF_NORMED, mask=m)
        r = np.nan_to_num(r, nan=-1, posinf=-1, neginf=-1)
        best = max(best, float(r.max()))
    return best


def similarity(fa, fb):
    hs = cv2.compareHist(fa[0].reshape(-1, 1).astype(np.float32),
                         fb[0].reshape(-1, 1).astype(np.float32), cv2.HISTCMP_CORREL)
    inter = np.minimum(fa[1], fb[1]).sum()
    union = np.maximum(fa[1], fb[1]).sum() + 1e-6
    return 0.6 * hs + 0.4 * (inter / union)


def analyze(img, protect_orders=True, producers=()):
    grid = {}
    orders = read_orders(img) if protect_orders else []
    cellimgs = {}
    for c, r, cell, center in cells(img):
        kind = classify(cell)
        gen = (c, r) in producers
        grid[(c, r)] = dict(kind=kind, center=center, protected=gen, producer=gen,
                            feat=feature(cell) if kind == ITEM else None)
        if kind == ITEM and not gen:
            cellimgs[(c, r)] = cell
    # 注文ごとに盤面アイテムを採点 → 最高一致の近くにいる物だけ保護
    small = {p: cv2.resize(cl, None, fx=MATCH_SCALE, fy=MATCH_SCALE, interpolation=cv2.INTER_AREA)
             for p, cl in cellimgs.items()}
    if len(_SCORE_CACHE) > 5000:
        _SCORE_CACHE.clear()
    for _, tmpl, okey in orders:
        scores = {}
        for p, cl in small.items():
            ck = (okey, hash(cl.tobytes()))
            if ck not in _SCORE_CACHE:
                _SCORE_CACHE[ck] = order_score(cl, tmpl)
            scores[p] = _SCORE_CACHE[ck]
        if not scores:
            break
        top = max(scores.values())
        for p, s in scores.items():
            if s >= ORDER_THRESHOLD and s >= top - ORDER_MARGIN:
                grid[p]["protected"] = True   # 注文の品 → 触らない
    grid["_orders"] = orders
    # アイテムをグループ化（貪欲クラスタリング）。注文の品は除外
    items = [k for k, v in grid.items() if k != "_orders" and v["kind"] == ITEM and not v["protected"]]
    groups, used = [], set()
    for i, a in enumerate(items):
        if a in used:
            continue
        g = [a]
        used.add(a)
        for b in items[i + 1:]:
            if b not in used and similarity(grid[a]["feat"], grid[b]["feat"]) >= SAME_THRESHOLD:
                g.append(b)
                used.add(b)
        groups.append(g)
    return grid, groups


def plan_merges(groups):
    """2個以上あるグループからペアを作る（近い順）"""
    moves = []
    for g in groups:
        g = sorted(g, key=lambda p: (p[1], p[0]))
        while len(g) >= 2:
            a = g.pop(0)
            b = min(g, key=lambda p: abs(p[0] - a[0]) + abs(p[1] - a[1]))
            g.remove(b)
            moves.append((a, b))
    return moves


# ---------------- 可視化 ----------------
COLORS = {EMPTY: (90, 90, 90), BOX: (40, 90, 160), JAR: (200, 120, 40)}


def annotate(img, grid, groups, moves):
    out = img.copy()
    gid = {p: i for i, g in enumerate(groups) for p in g if len(g) >= 2}
    rng = np.random.default_rng(3)
    pal = [tuple(int(x) for x in rng.integers(60, 255, 3)) for _ in range(64)]
    x0, y0, x1, y1 = board_rect(img)
    cw, ch = (x1 - x0) / COLS, (y1 - y0) / ROWS
    for (ox, oy, ow, oh), *_ in grid.get("_orders", []):
        cv2.rectangle(out, (ox - 4, oy - 4), (ox + ow + 4, oy + oh + 4), (0, 200, 255), 5)
    for key, v in grid.items():
        if key == "_orders":
            continue
        c, r = key
        a, b = int(x0 + c * cw), int(y0 + r * ch)
        e, f = int(a + cw), int(b + ch)
        if v.get("producer"):
            cv2.rectangle(out, (a + 3, b + 3), (e - 3, f - 3), (255, 255, 0), 8)
            cv2.putText(out, "GEN", (a + 8, b + 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 0), 3)
        elif v["kind"] == ITEM and v["protected"]:
            cv2.rectangle(out, (a + 3, b + 3), (e - 3, f - 3), (0, 200, 255), 8)
            cv2.putText(out, "ORDER", (a + 8, b + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 200, 255), 3)
        elif v["kind"] == ITEM:
            col = pal[gid[(c, r)] % 64] if (c, r) in gid else (255, 255, 255)
            cv2.rectangle(out, (a + 3, b + 3), (e - 3, f - 3), col, 6 if (c, r) in gid else 2)
            if (c, r) in gid:
                cv2.putText(out, f"G{gid[(c, r)]}", (a + 8, b + 34),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, col, 3)
        else:
            cv2.putText(out, v["kind"][:3], (a + 8, f - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, COLORS[v["kind"]], 2)
    for a, b in moves:
        cv2.arrowedLine(out, grid[a]["center"], grid[b]["center"], (0, 0, 255), 7, tipLength=0.15)
    return out


def show(win, img):
    try:
        h, w = img.shape[:2]
        cv2.imshow(win, cv2.resize(img, (int(w * 900 / h), 900)))
        cv2.waitKey(1)
    except cv2.error:
        pass  # Termux等ディスプレイ無し環境では何もしない


def is_termux():
    return "com.termux" in os.environ.get("PREFIX", "")


def empty_cells(img, grid):
    """空きマスの中央部の画像（生産品が着地したかの比較用）"""
    x0, y0, x1, y1 = board_rect(img)
    cw, ch = (x1 - x0) / COLS, (y1 - y0) / ROWS
    out = {}
    for key, v in grid.items():
        if key == "_orders" or v["kind"] != EMPTY:
            continue
        c, r = key
        a, b = int(x0 + (c + .2) * cw), int(y0 + (r + .2) * ch)
        out[key] = (a, b, int(cw * .6), int(ch * .6), img[b:b + int(ch * .6), a:a + int(cw * .6)].astype(np.int16))
    return out


def count_kind(grid, kind):
    return sum(1 for k, v in grid.items() if k != "_orders" and v["kind"] == kind)


def parse_cells(tokens):
    """['5,3','1,3'] or ['5','3'] → [(5,3),(1,3)]"""
    if all("," not in t for t in tokens):
        nums = [int(t) for t in tokens]
        if len(nums) % 2:
            raise SystemExit("--produce は 列,行 の組で指定して（例 --produce 5,3 1,3）")
        return [(nums[i], nums[i + 1]) for i in range(0, len(nums), 2)]
    out = []
    for t in tokens:
        c, r = t.split(",")
        out.append((int(c), int(r)))
    return out


# ---------------- メインループ ----------------
def count_dropped(empties, img):
    """前は空きだったマスのうち、物が置かれたマスの数"""
    n = 0
    for a, b, w, h, ref in empties.values():
        cur = img[b:b + h, a:a + w].astype(np.int16)
        if cur.shape == ref.shape and np.abs(cur - ref).mean() > CHANGE_DIFF:
            n += 1
    return n


def settle_count(empties, timeout=PRODUCE_TIMEOUT):
    """着地アニメが落ち着くまで見張り、最終的に埋まったマス数を返す"""
    end = time.time() + timeout
    time.sleep(0.5)
    last, stable = -1, 0
    while time.time() < end:
        n = count_dropped(empties, screencap())
        stable = stable + 1 if n == last else 0
        if n > 0 and stable >= 1:
            return n
        last = n
        time.sleep(PRODUCE_POLL)
    return max(last, 0)


def run(args):
    stop_file = os.path.expanduser(args.stop_file)
    if os.path.exists(stop_file):
        os.remove(stop_file)
    if args.start_delay:
        print(f"{args.start_delay}秒後に開始。今のうちにゲーム画面へ")
        time.sleep(args.start_delay)
    print(f"開始。止めるには Ctrl+C か `touch {args.stop_file}`")
    idle = hidden = merges = produced = 0
    last_prot = None
    producers = parse_cells(args.produce) if args.produce else []
    cooldown, fails = {}, {}
    cur = None            # いま使っている生産機（選択済みなら1タップ=1個なので使い続ける）
    phase = "merge"       # merge: ペアが尽きるまでマージ / produce: 空きが埋まるまで生産
    if producers:
        print(f"生産機: {producers}（マージ・移動しない）")
    while True:
        if os.path.exists(stop_file):
            print("停止ファイル検出。停止"); break
        t_cap = time.time()
        img = screencap()
        if not board_visible(img):
            hidden += 1
            print(f"盤面が見えない（ポップアップ/別アプリ？）→待機 {hidden}/{args.max_hidden}")
            if hidden >= args.max_hidden:
                print("盤面が戻らないので停止"); break
            time.sleep(2); continue
        hidden = 0
        t_an = time.time()
        grid, groups = analyze(img, protect_orders=not args.ignore_orders, producers=producers)
        moves = plan_merges(groups)
        n_empty = count_kind(grid, EMPTY)
        if args.verbose:
            print(f"[時間] 取得 {t_an - t_cap:.2f}s / 解析 {time.time() - t_an:.2f}s / ペア {len(moves)} / 空き {n_empty} / {phase}")
        prot = [k for k, v in grid.items() if k != "_orders" and v["protected"] and not v["producer"]]
        if prot and prot != last_prot:
            print(f"注文の品を保護中: {prot}")
        last_prot = prot
        view = annotate(img, grid, groups, moves)
        if args.save:
            cv2.imwrite(os.path.expanduser(args.save), view)
        if not args.no_view:
            show("kate-bot", view)

        # ---- 生産フェーズ：空きが埋まるまで連打。途中でペアができてもマージしない ----
        if phase == "produce":
            room = n_empty - args.keep_empty
            now = time.time()
            ready = [p for p in producers if cooldown.get(p, 0) <= now and grid[p]["kind"] == ITEM]
            if room <= 0 or not ready:
                if moves:
                    print(f"→ マージへ（{'空きなし' if room <= 0 else '生産機が全部休憩中'}）")
                    phase = "merge"
                elif room <= 0:
                    print("盤面が満杯でペアも無い。停止"); break
                else:
                    wait = min(30, max(1, min(cooldown.values()) - now)) if cooldown else 5
                    idle += 1
                    if idle > args.max_idle:
                        print("生産機が全部休憩中のまま。停止"); break
                    print(f"生産機が全部休憩中 → {wait:.0f}秒待機")
                    time.sleep(wait)
                    continue
            else:
                if cur not in ready:
                    cur = ready[0]
                n = min(args.burst, room)
                if args.max_produce:
                    n = min(n, args.max_produce - produced)
                print(f"生産機 {cur} を {n} 回タップ")
                if args.dry_run:
                    time.sleep(1.5); phase = "merge"; continue
                empties = empty_cells(img, grid)
                for _ in range(n):
                    tap(grid[cur]["center"])
                    time.sleep(args.tap_interval)
                got = settle_count(empties)
                produced += got
                print(f"  {got} 個出た（累計 {produced}）")
                if got == 0:
                    # 誤判定もあり得るので休憩は短く始めて連続失敗で伸ばす
                    fails[cur] = fails.get(cur, 0) + 1
                    rest = min(args.cooldown, 15 * 2 ** (fails[cur] - 1))
                    cooldown[cur] = time.time() + rest
                    print(f"  {cur} 反応なし → {rest}秒休ませる（連続{fails[cur]}回）")
                    if args.save:
                        cv2.imwrite(os.path.expanduser(args.save).replace(".png", "_nodrop.png"), screencap())
                    cur = None
                else:
                    fails[cur] = 0
                    idle = 0
                    if got < n - 1:   # 1回分は「選択タップ」の可能性があるので許容
                        cooldown[cur] = time.time() + args.depleted_rest
                        print(f"  {cur} は在庫切れっぽい → {args.depleted_rest}秒休ませて次へ")
                        cur = None
                if args.max_produce and produced >= args.max_produce:
                    print(f"{args.max_produce}個生産したので、マージだけして停止")
                    producers = []
                continue

        # ---- マージフェーズ：ペアが尽きるまで ----
        if not moves:
            if producers:
                phase = "produce"
                continue
            print("合体できるペアなし。停止"); break
        idle = 0
        if args.max_merges and merges >= args.max_merges:
            print(f"{args.max_merges}回マージしたので停止"); break
        # 重ならないペアは1回の読み取りでまとめて実行（マージは他のマスに影響しないため）
        batch = moves[:args.batch]
        if args.max_merges:
            batch = batch[:max(0, args.max_merges - merges)]
        for a, b in batch:
            merges += 1
            print(f"#{merges} merge {a} -> {b}")
            if not args.dry_run:
                swipe(grid[a]["center"], grid[b]["center"], args.swipe_ms)
                time.sleep(args.wait)
        if args.dry_run:
            time.sleep(1.5)
    print(f"合計 {merges} 回マージ / {produced} 個生産")


def main():
    global SERIAL
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyze", metavar="IMAGE", help="画像を解析して annotated.png を出力")
    ap.add_argument("--dry-run", action="store_true", help="スワイプせず認識だけ")
    ap.add_argument("--no-view", action="store_true", help="オーバーレイ窓を出さない")
    ap.add_argument("--produce", nargs="+", metavar="COL,ROW",
                    help="生産機のマス（0始まり、複数可 例: --produce 5,3 1,3）。順番にタップ")
    ap.add_argument("--max-produce", type=int, default=0, help="生産する個数の上限（0=無制限。エネルギー節約用）")
    ap.add_argument("--burst", type=int, default=6, help="生産フェーズで1回に連打する回数")
    ap.add_argument("--tap-interval", type=float, default=0.25, help="連打の間隔秒")
    ap.add_argument("--keep-empty", type=int, default=0, help="生産で埋めずに残す空きマス数")
    ap.add_argument("--depleted-rest", type=int, default=30, help="在庫切れっぽい生産機を休ませる秒数")
    ap.add_argument("--max-idle", type=int, default=20, help="全生産機休憩中の待機を何回で諦めるか")
    ap.add_argument("--cooldown", type=int, default=60, help="何も出なかった生産機を休ませる秒数")
    ap.add_argument("--serial", help="adb接続先（例 127.0.0.1:37123）。1台だけなら省略可")
    ap.add_argument("--start-delay", type=int, default=5 if is_termux() else 0,
                    help="開始前の待ち秒数（Termuxではゲームに切り替える猶予）")
    ap.add_argument("--save", default="~/storage/shared/Pictures/kate_bot_latest.png" if is_termux() else None,
                    help="毎手の認識結果画像の保存先")
    ap.add_argument("--stop-file", default="~/kate_stop")
    ap.add_argument("--max-hidden", type=int, default=15)
    ap.add_argument("--batch", type=int, default=BATCH, help="1回の読み取りで実行する最大手数（1=毎手読み直し）")
    ap.add_argument("--swipe-ms", type=int, default=SWIPE_MS, help="ドラッグ時間ms")
    ap.add_argument("--wait", type=float, default=WAIT_AFTER_MERGE, help="1手ごとの待ち秒")
    ap.add_argument("-v", "--verbose", action="store_true", help="取得・解析の所要時間を表示")
    ap.add_argument("--ignore-orders", action="store_true", help="注文の品も保護せずマージする")
    ap.add_argument("--max-merges", type=int, default=0, help="この回数マージしたら停止（0=無制限）")
    args = ap.parse_args()
    SERIAL = args.serial
    if is_termux():
        args.no_view = True

    if args.analyze:
        img = cv2.imread(args.analyze)
        print("board_visible:", board_visible(img))
        prods = parse_cells(args.produce) if args.produce else []
        grid, groups = analyze(img, protect_orders=not args.ignore_orders, producers=prods)
        moves = plan_merges(groups)
        print("orders:", [o[0] for o in grid["_orders"]])
        print("protected:", [k for k, v in grid.items() if k != "_orders" and v["protected"]])
        for r in range(ROWS):
            print(" ".join(f"{grid[(c, r)]['kind'][:3]:>5}" for c in range(COLS)))
        print("pairs:", moves)
        cv2.imwrite("annotated.png", annotate(img, grid, groups, moves))
        print("→ annotated.png")
        return
    try:
        run(args)
    except KeyboardInterrupt:
        print("\n停止")


if __name__ == "__main__":
    main()
