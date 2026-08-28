#!/usr/bin/env python3
"""
Build a readable HTML brew log from tommy_home_brewing.ods.

  python3 tools/build_brewlog.py

Output: brew-log/index.html + brew-log/<batch>.html
Source of truth stays the .ods; re-run after every log update.
Stdlib only + LibreOffice (soffice) for the CSV export.
"""
import csv, glob, html, os, re, shutil, subprocess, sys, tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ODS = os.path.join(ROOT, "tommy_home_brewing.ods")
OUT = os.path.join(ROOT, "brew-log")

# ── column groups (mirror the sheet's colour groups) ─────────────────────────
GROUPS = [
    ("基本",      ["批次", "釀造日", "配方·版本", "風格", "批量L"]),
    ("水與糖化",  ["水源", "鹽類 CaCl₂/石膏", "糖化溫°C", "糖化醪 pH", "發酵前 pH"]),
    ("熱端酒花",  ["苦花 0min", "旋渦 75°C"]),
    ("酵母投放",  ["酵母", "投法", "充氧 O₂", "營養劑 Fermaid", "ALDC"]),
    ("發酵",      ["OG", "發酵溫°C", "乾投@比重/日", "乾投酒花", "二次添加", "重力時間軸", "FG", "ABV%", "發酵度%"]),
    ("QA / 封裝", ["綠燈/雙乙醯", "Cold crash/熟成", "碳酸 PSI/°C", "封裝/2發日", "賞味期"]),
    ("評價",      ["評分", "心得/教訓"]),
]

# ── 1. export .ods → csv ──────────────────────────────────────────────────────
def export_csv():
    tmp = tempfile.mkdtemp(prefix="brewlog_")
    subprocess.run(
        ["soffice", "--headless", "--convert-to",
         'csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,false,false,false,-1',
         "--outdir", tmp, ODS],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    files = glob.glob(os.path.join(tmp, "*.csv"))
    f = [x for x in files if "批次" in x] or files
    rows = list(csv.reader(open(f[0], encoding="utf-8")))
    shutil.rmtree(tmp, ignore_errors=True)
    header = rows[0]
    batches = [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in rows[1:] if r and r[0].startswith("#")]
    return header, batches

# ── 2. gravity-point extraction (tolerant of the freeform log) ────────────────
SG = r"(1\.\d{3}|1\.\d{2}(?!\d))"

def first_sg(s):
    m = re.search(SG, s or "")
    return float(m.group(1)) if m else None

def parse_pitch_date(s):
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try: return datetime.strptime(s.strip()[:10], fmt)
        except Exception: pass
    return None

BAD_CONTEXT = ("預估", "目標", "窗口", "觸發", "計畫", "預期", "應停", "拉到", "落在")

def extract_points(b):
    """Return sorted list of (day_float, sg, label)."""
    pitch = parse_pitch_date(b.get("釀造日", ""))
    text = b.get("重力時間軸", "") or ""
    # refine pitch datetime if the log says e.g. "投酵母 8/26 21:55" (24:00 → next day 00:00)
    if pitch:
        pm = re.search(r"投酵母\s*(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})", text)
        if pm:
            mo, d, hh, mm = map(int, pm.groups())
            try:
                from datetime import timedelta
                pitch = datetime(pitch.year, mo, d) + timedelta(hours=hh, minutes=mm)
            except ValueError: pass
    # remove ranges like 1.040-1.030 / 1.045~1.035 so they never read as points
    clean = re.sub(r"1\.\d{3}\s*[-~–]\s*1\.\d{3}", " ", text)
    pts = []
    def ok(pos):
        return not any(k in clean[max(0, pos - 8):pos] for k in BAD_CONTEXT)

    # (a) hours since pitch: "(~38h)SG 1.020" / "(19h)1.052" / "+19h 1.010"(relative handled below)
    for m in re.finditer(r"[(（]~?(\d{1,3})h[)）][^0-9]{0,8}(?:SG\s*)?" + SG, clean):
        if ok(m.start()): pts.append((int(m.group(1)) / 24.0, float(m.group(2)), f"{m.group(1)}h"))
    # (b) date [time] ... SG: "8/27 ~17:00 ... 1.052", "7/31 00:30 1.038", "Day3 (6/28): SG 1.015"
    if pitch:
        for m in re.finditer(r"(\d{1,2})/(\d{1,2})(?:\s*~?(\d{1,2}):(\d{2}))?[^0-9]{0,12}(?:SG\s*|FG\s*)?" + SG, clean):
            if not ok(m.start()): continue
            mo, d = int(m.group(1)), int(m.group(2))
            yr = pitch.year + (1 if mo < pitch.month - 6 else 0)
            try: dt = datetime(yr, mo, d, int(m.group(3) or 0), int(m.group(4) or 0))
            except ValueError: continue
            day = (dt - pitch).total_seconds() / 86400
            if m.group(3) is None: day = round(day) + 0.5  # date only → assume midday
            if -0.5 <= day <= 60: pts.append((day, float(m.group(5)), f"{mo}/{d}"))
        # value then date: "1.03 (4/28)"
        for m in re.finditer(SG + r"\s*[(（](\d{1,2})/(\d{1,2})[)）]", clean):
            mo, d = int(m.group(2)), int(m.group(3))
            try: dt = datetime(pitch.year, mo, d)
            except ValueError: continue
            day = (dt - pitch).days + 0.5
            if 0 <= day <= 60: pts.append((day, float(m.group(1)), f"{mo}/{d}"))
    # (c) day markers: "d4:1.024", "Day3: 1.040", "Day0 OG 1.070"
    for m in re.finditer(r"[Dd](?:ay)?\s?(\d{1,2})\s*[:(（]?[^0-9]{0,10}(?:SG\s*|OG\s*)?" + SG, clean):
        if ok(m.start()): pts.append((float(m.group(1)) + (0 if m.group(1) == "0" else 0.5), float(m.group(2)), f"Day {m.group(1)}"))
    # (d) relative "+19h 1.010" → previous point + hours (needs order in text)
    prev_day = None
    for m in re.finditer(r"(?:[(（]~?(\d{1,3})h[)）]|(\d{1,2})/(\d{1,2})(?:\s*~?(\d{1,2}):(\d{2}))?|\+(\d{1,3})h)[^0-9]{0,12}(?:SG\s*)?" + SG, clean):
        if m.group(6) and prev_day is not None and ok(m.start()):
            pts.append((prev_day + int(m.group(6)) / 24.0, float(m.group(7)), f"+{m.group(6)}h"))
        elif m.group(1): prev_day = int(m.group(1)) / 24.0
        elif m.group(2) and pitch:
            try:
                dt = datetime(pitch.year, int(m.group(2)), int(m.group(3)), int(m.group(4) or 0), int(m.group(5) or 0))
                prev_day = (dt - pitch).total_seconds() / 86400 + (0.5 if m.group(4) is None else 0)
            except ValueError: pass
    # OG at day 0
    og = first_sg(b.get("OG", ""))
    if og: pts.append((0.0, og, "OG"))
    # dedupe (same day±0.15 & sg)
    out = []
    for d, sg, lab in sorted(pts):
        if any(abs(d - d2) < 0.15 and abs(sg - s2) < 0.0005 for d2, s2, _ in out): continue
        out.append((d, sg, lab))
    return out


# ── 2b. event extraction (vertical markers) ───────────────────────────────────
EVENT_KEYS = [("投酵母","投酵母"),("Fermaid","Fermaid-O"),("撈","撈袋"),("DH2","DH2"),("DH1","DH1"),("乾投","乾投"),
              ("藍莓","藍莓"),("香草","香草"),("果泥","果泥"),("綠燈","綠燈"),("轉桶","轉桶"),("水封","起泡"),
              ("D-rest","D-rest"),("升溫","升溫"),("cold crash","冷崩"),("Cold crash","冷崩")]

def _anchors(seg, pitch, prev_day):
    """All time anchors in a segment → list of (pos, day)."""
    out = []
    for m in re.finditer(r"[(（]~?(\d{1,3})h[)）]", seg):
        out.append((m.start(), int(m.group(1)) / 24.0))
    for m in re.finditer(r"\+(\d{1,3})h", seg):
        if prev_day is not None: out.append((m.start(), prev_day + int(m.group(1)) / 24.0))
    if pitch:
        for m in re.finditer(r"(\d{1,2})/(\d{1,2})(?:\s*~?(\d{1,2}):(\d{2}))?", seg):
            mo, d = int(m.group(1)), int(m.group(2))
            yr = pitch.year + (1 if mo < pitch.month - 6 else 0)
            try:
                dt = datetime(yr, mo, d, int(m.group(3) or 0) % 24, int(m.group(4) or 0))
                day = (dt - pitch).total_seconds() / 86400
                if m.group(3) is None: day = round(day) + 0.5
                if -0.5 <= day <= 60: out.append((m.start(), day))
            except ValueError: pass
    for m in re.finditer(r"[Dd](?:ay)?\s?(\d{1,2})\b", seg):
        out.append((m.start(), float(m.group(1)) + (0 if m.group(1) == "0" else 0.5)))
    return out

def _pitch_dt(b):
    pitch = parse_pitch_date(b.get("釀造日", ""))
    text = b.get("重力時間軸", "") or ""
    if pitch:
        pm = re.search(r"投酵母\s*(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})", text)
        if pm:
            mo, d, hh, mm = map(int, pm.groups())
            try:
                from datetime import timedelta
                pitch = datetime(pitch.year, mo, d) + timedelta(hours=hh, minutes=mm)
            except ValueError: pass
    return pitch

def extract_events(b):
    """Return sorted list of (day, label): each keyword binds to its nearest time anchor; same-day merged."""
    pitch = _pitch_dt(b)
    text = "\n".join(b.get(c, "") or "" for c in ("重力時間軸", "乾投@比重/日", "綠燈/雙乙醯", "封裝/2發日", "Cold crash/熟成"))
    raw, prev_day = [], None
    for seg in re.split(r"[。;\n|]|→", text):
        if not seg.strip() or any(k in seg for k in BAD_CONTEXT + ("預計", "尚未", "待")): continue
        anchors = _anchors(seg, pitch, prev_day)
        if not anchors: continue
        prev_day = anchors[-1][1]
        for k, lab in EVENT_KEYS:
            for m in re.finditer(re.escape(k), seg):
                pos, day = min(anchors, key=lambda a: abs(a[0] - m.start()))
                raw.append((day, lab))
    raw.sort()
    out = []
    for day, lab in raw:
        if out and abs(day - out[-1][0]) < 0.2:
            labs = out[-1][1]
            if lab not in labs: labs.append(lab)
        else:
            out.append([day, [lab]])
    res = []
    for day, labs in out:
        if "DH1" in labs or "DH2" in labs: labs = [l for l in labs if l != "乾投"]
        if "藍莓" in labs: labs = [l for l in labs if l != "果泥"]
        if "投酵母" in labs: labs = [l for l in labs if l != "起泡"]
        res.append((day, "+".join(labs)))
    return res

def expected_bands(b):
    """(dh_lo, dh_hi) DH1 window from 乾投@比重/日; expected FG (lo,hi) from notes."""
    dh = None
    m = re.search(r"(1\.\d{3})\s*[-~–]\s*(1\.\d{3})", b.get("乾投@比重/日", "") or "")
    if m: dh = tuple(sorted((float(m.group(1)), float(m.group(2)))))
    exp = None
    notes = (b.get("心得/教訓", "") or "") + " " + (b.get("重力時間軸", "") or "")
    m = re.search(r"預[估期]\s*FG\s*~?\s*(1\.\d{3})(?:\s*[-~–]\s*(1\.\d{3}))?", notes)
    if m: exp = (float(m.group(1)), float(m.group(2) or m.group(1)))
    return dh, exp

# ── 3. SVG chart ──────────────────────────────────────────────────────────────
def gravity_chart(pts, fg_actual=None, events=(), dh_band=None, exp_fg=None):
    if len(pts) < 2: return ""
    W, H, L, R, T, B = 640, 300, 52, 16, 52, 34
    days = [p[0] for p in pts] + [e[0] for e in events]
    sgs = [p[1] for p in pts]
    refs = [v for v in ([fg_actual] if fg_actual else []) + list(exp_fg or []) + list(dh_band or [])]
    xmax = max(2.0, max(days) * 1.08)
    lo = min(sgs + refs) - 0.004; hi = max(sgs + refs) + 0.004
    lo = int(lo * 200) / 200; hi = (int(hi * 200) + 1) / 200
    def X(d): return L + (d / xmax) * (W - L - R)
    def Y(v): return T + (hi - v) / (hi - lo) * (H - T - B)
    g = []
    # expected bands first (background)
    if dh_band:
        y1, y2 = Y(dh_band[1]), Y(dh_band[0])
        g.append(f'<rect x="{L}" y="{y1:.1f}" width="{W-L-R}" height="{y2-y1:.1f}" class="band"/>'
                 f'<text x="{L+6}" y="{y1+11:.1f}" class="bandlab">DH1 窗口 {dh_band[1]:.3f}–{dh_band[0]:.3f}</text>')
    step = 0.010 if hi - lo > 0.03 else 0.005
    v = lo
    while v <= hi + 1e-9:
        y = Y(v); g.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W-R}" y2="{y:.1f}" class="grid"/>'
                           f'<text x="{L-6}" y="{y+4:.1f}" class="tick" text-anchor="end">{v:.3f}</text>')
        v = round(v + step, 3)
    xt = 1 if xmax <= 12 else 2 if xmax <= 24 else 5
    d = 0
    while d <= xmax:
        g.append(f'<text x="{X(d):.1f}" y="{H-B+16}" class="tick" text-anchor="middle">{d}</text>'); d += xt
    g.append(f'<text x="{(L+W-R)/2:.0f}" y="{H-4}" class="axis-label" text-anchor="middle">投酵母後天數</text>')
    g.append(f'<line x1="{L}" y1="{Y(lo):.1f}" x2="{W-R}" y2="{Y(lo):.1f}" class="base"/>')
    if exp_fg:
        y1, y2 = Y(exp_fg[1]), Y(exp_fg[0])
        if abs(y2 - y1) < 1:
            g.append(f'<line x1="{L}" y1="{y1:.1f}" x2="{W-R}" y2="{y1:.1f}" class="expline"/>')
        else:
            g.append(f'<rect x="{L}" y="{y1:.1f}" width="{W-L-R}" height="{y2-y1:.1f}" class="expband"/>')
        g.append(f'<text x="{W-R}" y="{y1-4:.1f}" class="tick" text-anchor="end">預期 FG {exp_fg[0]:.3f}{"" if exp_fg[0]==exp_fg[1] else f"–{exp_fg[1]:.3f}"}</text>')
    if fg_actual:
        y = Y(fg_actual); g.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W-R}" y2="{y:.1f}" class="fgline"/>'
                                    f'<text x="{L+6}" y="{y-4:.1f}" class="tick">FG {fg_actual:.3f}</text>')
    # events: vertical hairlines + staggered labels in the top margin
    for i, (d, lab) in enumerate(events):
        x = X(d); yl = 14 + (i % 3) * 12
        g.append(f'<line x1="{x:.1f}" y1="{yl+3}" x2="{x:.1f}" y2="{Y(lo):.1f}" class="evline"/>'
                 f'<text x="{x+3:.1f}" y="{yl}" class="evlab">{html.escape(lab)}</text>')
    path = " ".join(f'{"M" if i==0 else "L"}{X(d):.1f},{Y(s):.1f}' for i, (d, s, _) in enumerate(pts))
    g.append(f'<path d="{path}" class="series"/>')
    for i, (d, s, lab) in enumerate(pts):
        g.append(f'<circle cx="{X(d):.1f}" cy="{Y(s):.1f}" r="4" class="pt" data-d="{d:.2f}" data-sg="{s:.3f}" data-lab="{html.escape(lab)}"/>')
        if i == 0 or i == len(pts) - 1:
            anchor = "start" if i == 0 else "end"; dx = 8 if i == 0 else -8
            g.append(f'<text x="{X(d)+dx:.1f}" y="{Y(s)+14:.1f}" class="dl" text-anchor="{anchor}">{s:.3f}</text>')
    legend = '<span class="lg"><i class="lg-pt"></i>實測比重</span>'
    if dh_band: legend += '<span class="lg"><i class="lg-band"></i>DH1 窗口(預期)</span>'
    if exp_fg: legend += '<span class="lg"><i class="lg-exp"></i>預期 FG</span>'
    if fg_actual: legend += '<span class="lg"><i class="lg-fg"></i>實際 FG</span>'
    if events: legend += '<span class="lg"><i class="lg-ev"></i>事件</span>'
    ev_rows = "".join(f"<tr><td>{d:.1f}</td><td>{html.escape(l)}</td></tr>" for d, l in events)
    return f'''<figure class="chart">
<figcaption>比重曲線 <span class="muted">(SG vs 投酵母後天數)</span><div class="legend">{legend}</div></figcaption>
<div class="chart-wrap"><svg viewBox="0 0 {W} {H}" role="img" aria-label="比重曲線">{''.join(g)}</svg><div class="tip" hidden></div></div>
<details class="tbl"><summary>資料表</summary><table><tr><th>時點</th><th>天數</th><th>SG</th></tr>{''.join(f"<tr><td>{html.escape(l)}</td><td>{d:.1f}</td><td>{s:.3f}</td></tr>" for d,s,l in pts)}</table>
{f'<table><tr><th>天數</th><th>事件</th></tr>{ev_rows}</table>' if events else ''}</details>
</figure>'''

# ── 4. HTML ───────────────────────────────────────────────────────────────────
CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--base:#c3c2b7;--border:rgba(11,11,11,.10);--s1:#2a78d6;--accent:#b45309;--tile:#f3f2ee}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;--surface:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--base:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;--accent:#f59e0b;--tile:#232322}}
:root[data-theme=dark]{color-scheme:dark;--surface:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--base:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;--accent:#f59e0b;--tile:#232322}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.6 system-ui,-apple-system,"Segoe UI","Noto Sans TC","Microsoft JhengHei",sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:24px 20px 48px}
a{color:var(--s1);text-decoration:none}a:hover{text-decoration:underline}
h1{font-size:24px;margin:0 0 4px}h2{font-size:15px;margin:22px 0 8px;color:var(--ink2);text-transform:none;letter-spacing:.3px}
.sub{color:var(--ink2);margin-bottom:16px}.muted{color:var(--muted);font-size:12px}
.nav{display:flex;justify-content:space-between;gap:12px;margin:8px 0 18px;font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:14px 0}
.tile{background:var(--tile);border:1px solid var(--border);border-radius:8px;padding:10px 12px}
.tile .k{font-size:11px;color:var(--muted)}.tile .v{font-size:22px;font-weight:600;margin-top:2px}.tile .v small{font-size:12px;color:var(--ink2);font-weight:400}
.chart{margin:16px 0;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 12px 6px}
.chart figcaption{font-size:13px;color:var(--ink2);margin-bottom:6px}
.chart-wrap{position:relative}.chart svg{width:100%;height:auto;display:block}
.grid{stroke:var(--grid);stroke-width:1}.base{stroke:var(--base);stroke-width:1}.tick{fill:var(--muted);font-size:10px;font-variant-numeric:tabular-nums}.axis-label{fill:var(--muted);font-size:11px}
.series{fill:none;stroke:var(--s1);stroke-width:2;stroke-linejoin:round}.pt{fill:var(--s1);stroke:var(--surface);stroke-width:2;cursor:pointer}.pt:hover{r:6}
.dl{fill:var(--ink2);font-size:11px;font-variant-numeric:tabular-nums}.fgline{stroke:var(--ink2);stroke-width:1.5;stroke-dasharray:6 4}.expline{stroke:var(--muted);stroke-width:1;stroke-dasharray:2 3}.expband{fill:var(--muted);fill-opacity:.10}.band{fill:var(--s1);fill-opacity:.09}.bandlab{fill:var(--s1);font-size:10px;opacity:.85}.evline{stroke:var(--accent);stroke-width:1;stroke-dasharray:2 3;opacity:.7}.evlab{fill:var(--accent);font-size:10px;font-weight:600}.legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:4px;font-size:11px;color:var(--ink2)}.lg i{display:inline-block;width:14px;height:8px;margin-right:4px;vertical-align:middle}.lg-pt{background:var(--s1);border-radius:4px;height:4px!important}.lg-band{background:var(--s1);opacity:.15}.lg-exp{border-top:1px dashed var(--muted);height:0!important}.lg-fg{border-top:1.5px dashed var(--ink2);height:0!important}.lg-ev{border-left:1px dashed var(--accent);width:0!important;height:10px!important}
.tip{position:absolute;pointer-events:none;background:var(--ink);color:var(--page);font-size:12px;padding:4px 8px;border-radius:4px;white-space:nowrap;transform:translate(-50%,-130%)}
details{border:1px solid var(--border);border-radius:8px;background:var(--surface);margin:8px 0;padding:0 12px}
summary{cursor:pointer;padding:9px 0;font-weight:600;font-size:14px}details[open] summary{border-bottom:1px solid var(--grid)}
dl{display:grid;grid-template-columns:130px 1fr;gap:6px 12px;margin:10px 0;font-size:13px}dt{color:var(--muted)}dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}
.tbl table,table.idx{width:100%;border-collapse:collapse;font-size:13px;margin:8px 0}.tbl th,.tbl td,table.idx th,table.idx td{padding:6px 8px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top}table.idx th{color:var(--muted);font-weight:500;font-size:12px}
table.idx tr:hover td{background:var(--tile)}.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;background:var(--tile);border:1px solid var(--border);color:var(--ink2)}
.notes{white-space:pre-wrap;font-size:13.5px;line-height:1.7}
@media(max-width:600px){dl{grid-template-columns:1fr}.wrap{padding:16px 12px 40px}}
"""
JS = """
document.querySelectorAll('.chart-wrap').forEach(w=>{const tip=w.querySelector('.tip');w.querySelectorAll('.pt').forEach(p=>{p.addEventListener('mouseenter',()=>{const r=p.getBoundingClientRect(),b=w.getBoundingClientRect();tip.textContent=p.dataset.lab+' · Day '+p.dataset.d+' · SG '+p.dataset.sg;tip.hidden=false;tip.style.left=(r.left-b.left+r.width/2)+'px';tip.style.top=(r.top-b.top)+'px';});p.addEventListener('mouseleave',()=>tip.hidden=true);});});
"""

def page(title, body, back=True):
    return f'''<!DOCTYPE html><html lang="zh-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class="wrap">
{'<div class="nav"><a href="index.html">← 批次索引</a><a href="../">酒譜首頁</a></div>' if back else ''}
{body}
</div><script>{JS}</script></body></html>'''

def esc(s): return html.escape((s or "").strip())

def batch_id(b): return b["批次"].lstrip("#")

def tile(k, v, small=""):
    return f'<div class="tile"><div class="k">{k}</div><div class="v">{v}{f" <small>{small}</small>" if small else ""}</div></div>'

def batch_page(b, prev_b, next_b):
    bid = batch_id(b)
    og, fg = first_sg(b["OG"]), first_sg(b["FG"])
    pts = extract_points(b)
    tiles = [tile("OG", esc(b["OG"]).split("(")[0] or "—"), tile("FG", esc(b["FG"]) or "—"),
             tile("ABV", f'{esc(b["ABV%"])}%' if b["ABV%"].strip() else "—"), tile("發酵度", f'{esc(b["發酵度%"])}%' if b["發酵度%"].strip() else "—"),
             tile("批量", f'{esc(b["批量L"]).split("(")[0]} L' if b["批量L"].strip() else "—")]
    secs = []
    for name, cols in GROUPS:
        if name == "基本": continue
        items = [(c, b.get(c, "")) for c in cols if b.get(c, "").strip()]
        if not items: continue
        if name == "評價":
            body = "".join(f'<div class="muted" style="margin-top:8px">{esc(c)}</div><div class="notes">{esc(v)}</div>' for c, v in items)
            secs.append(f'<details open><summary>{name}</summary>{body}</details>')
        else:
            body = "<dl>" + "".join(f"<dt>{esc(c)}</dt><dd>{esc(v)}</dd>" for c, v in items) + "</dl>"
            secs.append(f'<details{" open" if name=="發酵" else ""}><summary>{name}</summary>{body}</details>')
    prev_link = '<a href="%s.html">← %s</a>' % (batch_id(prev_b), esc(prev_b["批次"])) if prev_b else ""
    next_link = '<a href="%s.html">%s →</a>' % (batch_id(next_b), esc(next_b["批次"])) if next_b else ""
    nav = f'<div class="nav"><span>{prev_link}</span><span>{next_link}</span></div>'
    body = f'''<h1>{esc(b["批次"])} · {esc(b["配方·版本"])}</h1>
<div class="sub">{esc(b["風格"])} <span class="badge">{esc(b["釀造日"])}</span> {f'<span class="badge">{esc(b["評分"])}</span>' if b["評分"].strip() else ""}</div>
<div class="tiles">{''.join(tiles)}</div>
{gravity_chart(pts, fg, extract_events(b), *expected_bands(b))}
{''.join(secs)}
{nav}'''
    return page(f'{b["批次"]} {b["配方·版本"]} — Brew Log', body)

def index_page(batches):
    rows = []
    for b in reversed(batches):
        og, fg = first_sg(b["OG"]), first_sg(b["FG"])
        rows.append(f'<tr><td><a href="{batch_id(b)}.html"><b>{esc(b["批次"])}</b></a></td><td class="num">{esc(b["釀造日"])}</td>'
                    f'<td>{esc(b["配方·版本"])}<div class="muted">{esc(b["風格"])}</div></td>'
                    f'<td class="num">{og and f"{og:.3f}" or "—"} → {fg and f"{fg:.3f}" or "—"}</td>'
                    f'<td class="num">{esc(b["ABV%"]) or "—"}</td><td>{esc(b["評分"]).split("(")[0] or "—"}</td></tr>')
    body = f'''<h1>🍺 Brew Log</h1><div class="sub">每批一頁 · 比重曲線 · 資料來源 <code>tommy_home_brewing.ods</code>(改完重跑 <code>tools/build_brewlog.py</code>)</div>
<table class="idx"><tr><th>批次</th><th>釀造日</th><th>配方 / 風格</th><th>OG → FG</th><th>ABV%</th><th>評分</th></tr>{''.join(rows)}</table>
<div class="muted" style="margin-top:14px">產生時間 {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>'''
    return page("Brew Log — 批次索引", body, back=False)

def main():
    header, batches = export_csv()
    os.makedirs(OUT, exist_ok=True)
    for i, b in enumerate(batches):
        prev_b = batches[i - 1] if i > 0 else None
        next_b = batches[i + 1] if i + 1 < len(batches) else None
        with open(os.path.join(OUT, f"{batch_id(b)}.html"), "w", encoding="utf-8") as f:
            f.write(batch_page(b, prev_b, next_b))
        pts = extract_points(b)
        ev = extract_events(b)
        print(f'{b["批次"]:9s} points={len(pts):2d}  ' + ", ".join(f"{l}:{s:.3f}@{d:.1f}" for d, s, l in pts) + (f"\n{'':10s}events: " + ", ".join(f"{l}@{d:.1f}" for d, l in ev) if ev else ""))
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_page(batches))
    print(f"→ {OUT}/index.html + {len(batches)} pages")

if __name__ == "__main__":
    main()
