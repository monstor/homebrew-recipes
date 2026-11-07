#!/usr/bin/env python3
"""RAPT Pill 的 Custom Data Stream 接收器(每 15 分鐘一筆 POST)。

用法:
    RAPT_PATH=<密徑> python3 tools/rapt_receiver.py   # 監聽 127.0.0.1:8787
    sudo tailscale funnel --bg --https=8443 http://127.0.0.1:8787

endpoint 掛在公網,所以 RAPT_PATH 設一段亂碼當密徑,只有 URL 結尾符合的
請求才收,其他一律 403。實際值在 white-piz 的 systemd unit 裡,不入版控。

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

# 這個 endpoint 掛在公網(Tailscale Funnel),所以只收帶密徑的請求,
# 其他路徑一律 403 —— 否則任何人都能往釀造記錄塞垃圾資料。
PATH_TOKEN = os.environ.get('RAPT_PATH', '')
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
    def ok_path(self):
        if not PATH_TOKEN:
            return True
        if self.path.rstrip('/').endswith(PATH_TOKEN):
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
        if not self.ok_path():
            return
        body = f'rapt receiver up; {sum(1 for _ in RAW.open()) if RAW.exists() else 0} readings\n'.encode()
        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 關掉預設的 stderr 噪音
        pass


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    print(f'listening on 127.0.0.1:{PORT} → {OUT}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
