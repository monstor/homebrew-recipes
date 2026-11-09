#!/usr/bin/env python3
"""RAPT Pill 的 Custom Data Stream 接收器(每 15 分鐘一筆 POST)。

用法:
    RAPT_PATH=<密徑> python3 tools/rapt_receiver.py   # 監聽 127.0.0.1:8787
    sudo tailscale funnel --bg --https=8443 http://127.0.0.1:8787

GET /<密徑>              → 一行健康檢查
GET /<密徑>/chart        → 當前批次的比重+溫度曲線圖(HTML,圖直接畫在頁面裡)
GET /<密徑>/chart/<批次> → 指定批次,例如 /chart/0012
曲線圖要用手機看,RAPT_BIND 要加上這台機器的 Tailscale IP(見下面 BINDS)。

endpoint 掛在公網,所以 RAPT_PATH 設一段亂碼當密徑,只有 URL 結尾符合的
請求才收,其他一律 403。實際值在 white-piz 的 systemd unit 裡,不入版控。

RAPT 的 Custom webhook payload 格式官方沒有文件,所以本腳本:
  1. 先把**原始 JSON 整筆**存進 <批次>/raw.jsonl —— 任何欄位都不會遺失
  2. 再盡力從常見欄位名猜出比重/溫度/電量,寫成 <批次>/readings.csv 方便看
第一筆真實資料進來後,照 raw.jsonl 的實際欄位名把 FIELDS 改精準即可。

檔案照批次分資料夾,批次號讀 rapt-data 旁邊的 CURRENT_BATCH 文字檔:
    rapt-data/0012/readings.csv + raw.jsonl
    rapt-data/unassigned/...      ← CURRENT_BATCH 不存在或空的時候
開釀時只要改 CURRENT_BATCH 的內容就換批,不必重啟服務。

資料不會因為這台機器睡著而遺失:RAPT 雲端與手機 App 永遠留有完整歷史,
這份只是給自動化看的副本。
"""
import json, csv, os, pathlib, datetime, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 資料目錄:預設放腳本上一層的 rapt-data/,可用 RAPT_OUT 覆寫(white-piz 用這個)
OUT = pathlib.Path(os.environ.get('RAPT_OUT') or
                   pathlib.Path(__file__).resolve().parent.parent / 'rapt-data')

# 這個 endpoint 掛在公網(Tailscale Funnel),所以只收帶密徑的請求,
# 其他路徑一律 403 —— 否則任何人都能往釀造記錄塞垃圾資料。
PATH_TOKEN = os.environ.get('RAPT_PATH', '')
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787

# 綁哪些位址,逗號分隔。127.0.0.1 是 Funnel 轉進來的入口,一定要留;
# 要用手機看曲線圖就再加這台機器的 Tailscale IP(100.x.x.x)——
# 只有自己的裝置連得到,區網其他機器連不到。不要寫 0.0.0.0,那會開給整個區網。
BINDS = [a.strip() for a in os.environ.get('RAPT_BIND', '127.0.0.1').split(',') if a.strip()]

# 批次號放在 CURRENT_BATCH 這個小文字檔裡(例如內容就是 0012),每筆資料都重讀
# 一次 → 開釀時改那個檔就換批,不必重啟服務。沒有檔或是空的就落在 unassigned/。
# 照批次分而不照天分:釀造紀錄本來就是一批一列,照天分之後還要自己拼回去。
BATCH_FILE = pathlib.Path(os.environ.get('RAPT_BATCH_FILE') or OUT.parent / 'CURRENT_BATCH')


def batch_dir():
    try:
        name = BATCH_FILE.read_text(encoding='utf-8').strip().splitlines()[0].strip()
    except Exception:
        name = ''
    safe = ''.join(c for c in name if c.isalnum() or c in '-_#') or 'unassigned'
    d = OUT / safe.lstrip('#')
    d.mkdir(parents=True, exist_ok=True)
    return d

# 候選欄位名(RAPT 未公開格式 → 多猜幾個,取第一個有值的)
FIELDS = {
    'sg':        ('gravity',),
    'temp_c':    ('temperature',),
    'battery':   ('battery',),
    'rssi':      ('rssi',),
    'device':    ('name', 'deviceId'),
    'device_utc': ('timestamp',),
}
COLS = ['received_utc', 'device_utc', 'sg', 'temp_c', 'battery', 'rssi', 'device']

# DH1 的投放窗口(比重降到 OG 一半附近)。圖上畫成一條帶子,一眼看出到了沒。
DH1_LO, DH1_HI = 1.028, 1.038   # 只在還沒有 OG 可算的時候當預設(= #0012 的窗口)


def dh1_window(rows):
    """DH1 的投放窗口 = 「OG 降一半」± 0.005,照這批自己的 OG 算,不寫死。

    規則出自酒譜本身(orange-glow/brew-sheet.html:「到 1.038-1.028(OG 1.066
    降一半 ≈1.033)立刻投」)。OG 取這批第一筆讀數 —— Pill 開釀就下桶,
    第一筆就是 OG;還沒有資料就退回預設值。
    """
    sgs = [r['sg'] for r in rows if r['sg'] is not None]
    if not sgs or sgs[0] <= 1.0:
        return DH1_LO, DH1_HI, None
    og = sgs[0]
    half = 1.0 + (og - 1.0) / 2
    return round(half - 0.005, 3), round(half + 0.005, 3), og


def read_rows(d):
    f = d / 'readings.csv'
    if not f.exists():
        return []
    out = []
    with f.open(encoding='utf-8', newline='') as fh:
        for r in csv.DictReader(fh):
            try:
                t = datetime.datetime.fromisoformat(
                    (r.get('device_utc') or r['received_utc']).replace('Z', '+00:00'))
            except Exception:
                continue
            def num(k):
                try:
                    return float(r.get(k) or '')
                except ValueError:
                    return None
            out.append({'t': t, 'sg': num('sg'), 'temp': num('temp_c'),
                        'batt': num('battery'), 'dev': r.get('device') or ''})
    out.sort(key=lambda r: r['t'])
    return out


def abv(og, sg):
    """ABV 不在封包裡(RAPT 網頁也是算的):(OG − SG) × 131.25,OG 取第一筆讀數。"""
    if not og or not sg or og <= 1.0 or sg > og:
        return None
    return (og - sg) * 131.25


def svg_chart(rows, w=880, h=380, pad=58):
    """手繪 inline SVG:比重(左軸)+ 溫度(右軸)。不外連任何 CDN,離線可看。"""
    d_lo, d_hi, _og = dh1_window(rows)
    pts = [r for r in rows if r['sg'] is not None]
    if len(pts) < 2:
        return '<p class="muted">資料還不足以畫圖(至少要兩筆有比重的讀數)。</p>'
    t0, t1 = pts[0]['t'], pts[-1]['t']
    span = max((t1 - t0).total_seconds(), 1.0)
    sgs = [r['sg'] for r in pts]
    lo, hi = min(sgs + [d_lo]), max(sgs + [d_hi])
    m = max((hi - lo) * 0.12, 0.004)
    lo, hi = lo - m, hi + m
    # 右軸固定 0-100:酒溫(°C)、ABV(%)、電量(%)三者量級相同,共用一條真實刻度,
    # 不做任何正規化 —— 縮放過的線看起來好看,但讀出來的數字是假的。
    tlo, thi = 0.0, 100.0
    og = pts[0]['sg']
    padr = 104   # 右側留白:線尾數值標籤 + 右軸刻度各佔一半
    iw, ih = w - pad - padr, h - 2 * pad

    def x(t):
        return pad + iw * (t - t0).total_seconds() / span

    def ysg(v):
        return pad + ih * (hi - v) / (hi - lo)

    def ytemp(v):
        return pad + ih * (thi - v) / (thi - tlo)

    p = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="比重與溫度曲線">']
    # DH1 窗口帶
    yb, yt = ysg(d_lo), ysg(d_hi)
    p.append(f'<rect x="{pad}" y="{yt:.1f}" width="{iw}" height="{yb - yt:.1f}" '
             f'fill="var(--band)"/>')
    p.append(f'<text x="{pad + 6}" y="{min(yt + 14, yb - 4):.1f}" class="lbl">DH1 窗口 '
             f'{d_hi:.3f}–{d_lo:.3f}</text>')
    # 軸與格線
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        y = ysg(v)
        p.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{pad + iw}" y2="{y:.1f}" class="grid"/>')
        p.append(f'<text x="{pad - 8}" y="{y + 4:.1f}" class="ax" text-anchor="end">{v:.3f}</text>')
        tv = tlo + (thi - tlo) * i / 4   # 右軸與左軸同向:都是下面小、上面大
        p.append(f'<text x="{pad + iw + 56}" y="{y + 4:.1f}" class="ax t">{tv:.0f}</text>')
    hours = span / 3600
    step = max(round(hours / 6), 1)
    k = 0
    while k * step <= hours:
        t = t0 + datetime.timedelta(hours=k * step)
        p.append(f'<text x="{x(t):.1f}" y="{pad + ih + 20}" class="ax" text-anchor="middle">'
                 f'{k * step}h</text>')
        k += 1
    # 溫度線(先畫,壓在比重下面)
    for key, cls, val in (('batt', 'lbatt', lambda r: r['batt']),
                          ('temp', 'ltemp', lambda r: r['temp']),
                          ('sg',   'labv',  lambda r: abv(og, r['sg']))):
        sp = [(r['t'], val(r)) for r in rows if r.get(key) is not None]
        sp = [(t, v) for t, v in sp if v is not None]
        if len(sp) > 1:
            d = ' '.join(f'{x(t):.1f},{ytemp(v):.1f}' for t, v in sp)
            p.append(f'<polyline points="{d}" class="{cls}"/>')
            p.append(f'<text x="{pad + iw + 6}" y="{ytemp(sp[-1][1]) + 3:.1f}" '
                     f'class="vl v-{cls[1:]}">{sp[-1][1]:.1f}</text>')
    d = ' '.join(f'{x(r["t"]):.1f},{ysg(r["sg"]):.1f}' for r in pts)
    p.append(f'<polyline points="{d}" class="lsg"/>')
    last = pts[-1]
    p.append(f'<circle cx="{x(last["t"]):.1f}" cy="{ysg(last["sg"]):.1f}" r="4" class="dot"/>')
    p.append(f'<text x="{pad + iw + 56}" y="{pad - 14}" class="ax t">°C / %</text>')
    p.append(f'<text x="{pad - 8}" y="{pad - 14}" class="ax" text-anchor="end">比重</text>')
    p.append('</svg>')
    return ''.join(p)


CSS = """:root{--bg:#fbfaf7;--fg:#23201c;--mut:#7c756b;--line:#e3ded4;--sg:#b4530a;
--temp:#2f6f8f;--abv:#2f7d4f;--batt:#8a8378;--band:rgba(180,83,10,.10);--card:#fff}
@media(prefers-color-scheme:dark){:root{--bg:#191714;--fg:#ece7df;--mut:#9c948a;
--line:#332f29;--card:#211e1a;--sg:#f0923c;--temp:#6fb4d4;--abv:#6cbd8c;
--batt:#9c948a;--band:rgba(240,146,60,.14)}}
*{box-sizing:border-box}
body{margin:0;padding:20px 16px 40px;background:var(--bg);color:var(--fg);
font:15px/1.55 -apple-system,"Helvetica Neue","PingFang TC","Noto Sans TC",sans-serif}
.wrap{max-width:920px;margin:0 auto}
h1{font-size:19px;margin:0 0 2px}
.muted{color:var(--mut);font-size:13px;margin:0 0 16px}
.tiles{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 18px}
.tile{flex:1 1 120px;background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:10px 12px}
.tile b{display:block;font-size:11px;color:var(--mut);font-weight:600;
letter-spacing:.04em;text-transform:uppercase}
.tile span{font-size:22px;font-variant-numeric:tabular-nums}
.chart{width:100%;height:auto;background:var(--card);border:1px solid var(--line);
border-radius:10px}
.grid{stroke:var(--line);stroke-width:1}
.ax{fill:var(--mut);font-size:11px}
.ax.t{fill:var(--temp)}
.lbl{fill:var(--sg);font-size:10px}
.lsg{fill:none;stroke:var(--sg);stroke-width:2.5;stroke-linejoin:round}
.ltemp{fill:none;stroke:var(--temp);stroke-width:1.5;stroke-dasharray:4 3}
.labv{fill:none;stroke:var(--abv);stroke-width:1.5}
.lbatt{fill:none;stroke:var(--batt);stroke-width:1.2;stroke-dasharray:1 3}
.vl{font-size:10px;font-weight:600;stroke:none}
.vl.v-temp{fill:var(--temp)}.vl.v-abv{fill:var(--abv)}.vl.v-batt{fill:var(--batt)}
.dot{fill:var(--sg)}
.key{font-size:12px;color:var(--mut);margin:8px 0 20px}
.key i{display:inline-block;width:18px;height:3px;vertical-align:middle;margin-right:5px}
table{width:100%;border-collapse:collapse;font-size:13px;
font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right}
th:first-child,td:first-child{text-align:left}
th{color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase}
@media(max-width:560px){.tile span{font-size:18px}}"""


def chart_page(d, rows, batches=(), base=''):
    def fmt(v, dp=3, suf=''):
        return f'{v:.{dp}f}{suf}' if isinstance(v, float) else '—'
    last = rows[-1] if rows else {}
    sgs = [r for r in rows if r['sg'] is not None]
    first_sg = sgs[0]['sg'] if sgs else None
    cur = last.get('sg')
    att = ''
    if first_sg and cur and first_sg > 1.0:
        att = f'{(first_sg - cur) / (first_sg - 1.0) * 100:.0f}%'
    age = '—'
    if rows:
        mins = (datetime.datetime.now(datetime.timezone.utc) - last['t']).total_seconds() / 60
        # 裝置時鐘可能比本機快幾秒,算出負數就寫「剛剛」
        age = ('剛剛' if mins < 1 else
               f'{mins:.0f} 分鐘前' if mins < 180 else f'{mins / 60:.1f} 小時前')
    elapsed = f'{(rows[-1]["t"] - rows[0]["t"]).total_seconds() / 3600:.1f} h' if len(rows) > 1 else '—'
    d_lo, d_hi, og = dh1_window(rows)
    dh1 = '—'
    if isinstance(cur, float):
        dh1 = ('已過站(低於窗口)' if cur < d_lo else
               '★ 到了,投 DH1' if cur <= d_hi else '還沒到')
    a = abv(first_sg, cur) if (first_sg and cur) else None
    tiles = [('批次', d.name), ('比重', fmt(cur)), ('酒溫', fmt(last.get('temp'), 1, '°C')),
             ('ABV', f'{a:.1f}%' if a is not None else '—'),
             ('發酵度', att or '—'), ('DH1', dh1), ('電量', fmt(last.get('batt'), 0, '%')),
             ('筆數', str(len(rows))), ('最新讀數', age), ('經過', elapsed)]
    rowsrev = rows[::-1][:24]
    trs = ''.join(
        f'<tr><td>{r["t"].astimezone().strftime("%m/%d %H:%M")}</td>'
        f'<td>{fmt(r["sg"])}</td><td>{fmt(r["temp"],1)}</td>'
        f'<td>{fmt(r["batt"],0)}</td></tr>' for r in rowsrev)
    ogtxt = f'(OG {og:.3f} 降一半 ±0.005)' if og else '(預設值,還沒有 OG 可算)'
    nav = ''
    if len(batches) > 1:
        nav = '<p class="muted">其他批次:' + ' '.join(
            f'<a href="{base}/{b}">{b}</a>' if b != d.name else f'<b>{b}</b>'
            for b in batches) + '</p>'
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pill {d.name}</title><style>{CSS}</style>
<meta http-equiv="refresh" content="300"></head><body><div class="wrap">
<h1>RAPT Pill — 批次 {d.name}</h1>
{svg_chart(rows)}
<p class="key"><i style="background:var(--sg)"></i>比重(左軸)
&nbsp;&nbsp;<i style="background:var(--temp)"></i>酒溫 °C
&nbsp;&nbsp;<i style="background:var(--abv)"></i>ABV %
&nbsp;&nbsp;<i style="background:var(--batt)"></i>電量 %
<span class="muted">(後三者共用右軸 0–100,未經縮放)</span>
&nbsp;&nbsp;<span style="color:var(--sg)">▇</span> DH1 窗口 {d_hi:.3f}–{d_lo:.3f}{ogtxt}</p>
<div class="tiles">{''.join(f'<div class="tile"><b>{k}</b><span>{v}</span></div>' for k, v in tiles)}</div>
<table><thead><tr><th>時間</th><th>比重</th><th>溫度</th><th>電量</th></tr></thead>
<tbody>{trs or '<tr><td colspan="4">還沒有資料</td></tr>'}</tbody></table>
<p class="muted">每 15 分鐘一筆,本頁 5 分鐘自動重新整理。時間為本地時間(Asia/Taipei)。
DH1 窗口照這批自己的 OG 算:OG 降一半 ±0.005,規則出自酒譜。</p>
{nav}
</div></body></html>"""


def pick(d, keys):
    """RAPT 的量測值包在 data 底下,裝置資訊在最外層,所以兩層都找。"""
    if not isinstance(d, dict):
        return ''
    for src in (d, d.get('data')):
        if isinstance(src, dict):
            for k in keys:
                if src.get(k) is not None:
                    return src[k]
    return ''


class Handler(BaseHTTPRequestHandler):
    def ok_path(self):
        if not PATH_TOKEN:
            return True
        # 密徑出現在路徑的任一段就算過(POST 是 /<密徑>,圖是 /<密徑>/chart/<批次>)
        if PATH_TOKEN in [p for p in self.path.split('?')[0].split('/') if p]:
            return True
        self.send_response(403); self.send_header('Content-Length', '0'); self.end_headers()
        print(f'403 {self.command} {self.path}', flush=True)
        return False

    def do_POST(self):
        if not self.ok_path():
            return
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
        d = batch_dir()
        raw, csvf = d / 'raw.jsonl', d / 'readings.csv'
        try:
            data = json.loads(body)
        except Exception:
            data = {'_unparsed': body.decode('utf-8', 'replace')}
        # headers 一起存:RAPT 的簽章 header 與 content-type 只能從真實封包看到
        with raw.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'received_utc': now, 'path': self.path,
                                'headers': dict(self.headers.items()), 'payload': data},
                               ensure_ascii=False) + '\n')
        row = {'received_utc': now}
        row.update({k: pick(data, v) for k, v in FIELDS.items()})
        new = not csvf.exists()
        with csvf.open('a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction='ignore')
            if new:
                w.writeheader()
            w.writerow(row)
        print(f'{now}  [{d.name}]  sg={row["sg"]}  temp={row["temp_c"]}  batt={row["battery"]}', flush=True)
        self.send_response(200); self.send_header('Content-Length', '2'); self.end_headers()
        self.wfile.write(b'ok')

    def reply(self, body, ctype='text/plain; charset=utf-8', code=200):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        """兩種 GET:/<密徑> 是健康檢查,/<密徑>/chart[/<批次>] 是曲線圖。"""
        if not self.ok_path():
            return
        parts = [p for p in self.path.split('?')[0].split('/') if p]
        if 'chart' not in parts:
            d = batch_dir()
            raw = d / 'raw.jsonl'
            n = sum(1 for _ in raw.open(encoding='utf-8')) if raw.exists() else 0
            self.reply(f'rapt receiver up; batch={d.name}; {n} readings\n')
            return
        # 曲線圖只在 tailnet 這張網路卡上服務。Funnel 是從 127.0.0.1 轉進來的,
        # 不擋的話 Funnel 一開,公網就看得到這頁(密徑外流即全開)。
        if self.server.server_address[0].startswith('127.'):
            self.reply('chart 只開在 tailnet,不經過 Funnel。\n', code=403)
            return
        i = parts.index('chart')
        base = '/' + '/'.join(parts[:i + 1])
        batches = sorted(p.name for p in OUT.iterdir() if p.is_dir()) if OUT.exists() else []
        want = parts[i + 1] if len(parts) > i + 1 else ''
        d = OUT / want if want in batches else batch_dir()
        self.reply(chart_page(d, read_rows(d), batches, base),
                   'text/html; charset=utf-8')

    def log_message(self, *a):  # 關掉預設的 stderr 噪音
        pass


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    print(f'listening on {", ".join(f"{a}:{PORT}" for a in BINDS)} → {OUT}  (batch file: {BATCH_FILE})',
          flush=True)
    servers = [ThreadingHTTPServer((a, PORT), Handler) for a in BINDS]
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    servers[0].serve_forever()
