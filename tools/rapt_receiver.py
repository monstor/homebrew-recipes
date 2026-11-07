#!/usr/bin/env python3
"""RAPT Pill 的 Custom Data Stream 接收器(每 15 分鐘一筆 POST)。

用法:
    python3 tools/rapt_receiver.py            # 監聽 127.0.0.1:8787
    tailscale funnel 8787                     # 另一個終端:把它開成對外 HTTPS

RAPT 的 Custom webhook payload 格式官方沒有文件,所以本腳本:
  1. 先把**原始 JSON 整筆**存進 rapt-data/raw.jsonl —— 任何欄位都不會遺失
  2. 再盡力從常見欄位名猜出比重/溫度/電量,寫成 rapt-data/readings.csv 方便看
第一筆真實資料進來後,照 raw.jsonl 的實際欄位名把 FIELDS 改精準即可。

資料不會因為這台機器睡著而遺失:RAPT 雲端與手機 App 永遠留有完整歷史,
這份只是給自動化看的副本。
"""
import json, csv, os, pathlib, datetime, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 資料目錄:預設放腳本上一層的 rapt-data/,可用 RAPT_OUT 覆寫(白皮機用這個)
OUT = pathlib.Path(os.environ.get('RAPT_OUT') or
                   pathlib.Path(__file__).resolve().parent.parent / 'rapt-data')
RAW, CSVF = OUT / 'raw.jsonl', OUT / 'readings.csv'
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787

# 候選欄位名(RAPT 未公開格式 → 多猜幾個,取第一個有值的)
FIELDS = {
    'sg':      ('gravity', 'sg', 'specificGravity', 'gravityVelocity'),
    'temp_c':  ('temperature', 'temp', 'temperatureCelsius'),
    'battery': ('battery', 'batteryLevel', 'batteryPercent'),
    'rssi':    ('rssi', 'signalStrength'),
    'device':  ('name', 'deviceName', 'macAddress', 'id'),
}
COLS = ['received_utc', 'sg', 'temp_c', 'battery', 'rssi', 'device']


def pick(d, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return ''


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
        OUT.mkdir(exist_ok=True)
        try:
            data = json.loads(body)
        except Exception:
            data = {'_unparsed': body.decode('utf-8', 'replace')}
        with RAW.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'received_utc': now, 'payload': data}, ensure_ascii=False) + '\n')
        row = {'received_utc': now}
        row.update({k: pick(data, v) for k, v in FIELDS.items()})
        new = not CSVF.exists()
        with CSVF.open('a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction='ignore')
            if new:
                w.writeheader()
            w.writerow(row)
        print(f'{now}  sg={row["sg"]}  temp={row["temp_c"]}  batt={row["battery"]}', flush=True)
        self.send_response(200); self.send_header('Content-Length', '2'); self.end_headers()
        self.wfile.write(b'ok')

    def do_GET(self):  # 給 tailscale funnel / 自己測活著沒
        body = f'rapt receiver up; {sum(1 for _ in RAW.open()) if RAW.exists() else 0} readings\n'.encode()
        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 關掉預設的 stderr 噪音
        pass


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    print(f'listening on 127.0.0.1:{PORT} → {OUT}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
