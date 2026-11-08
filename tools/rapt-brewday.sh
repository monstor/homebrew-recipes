#!/usr/bin/env bash
# 開釀日的單一指令(跑在 white-piz)。批次號當參數帶進去,網址自己算。
#
#   ./rapt-brewday.sh start 0012   設批次 → 啟動接收器 → 開 Funnel → 印出兩個網址
#   ./rapt-brewday.sh status       哪一批、服務在不在、公網開著沒、最新一筆
#   ./rapt-brewday.sh stop         關 Funnel → 停接收器(Pill 離桶後跑)
#
# 只有開關 Funnel 要 sudo(會問一次密碼),其餘都是使用者層的 systemd。
# 密徑從 systemd unit 的 RAPT_PATH 讀,不寫在這個檔裡 —— 這支腳本進版控。
set -euo pipefail

UNIT=rapt-receiver
RAPT_HOME=${RAPT_HOME:-$HOME/rapt}
LOCAL_PORT=${RAPT_PORT:-8787}
FUNNEL_PORT=${RAPT_FUNNEL_PORT:-8443}

die() { echo "✗ $*" >&2; exit 1; }

token() {
  systemctl --user show -p Environment "$UNIT" 2>/dev/null |
    tr ' ' '\n' | sed -n 's/^RAPT_PATH=//p' | head -1
}

dnsname() {
  tailscale status --json 2>/dev/null |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'
}

batch() { cat "$RAPT_HOME/CURRENT_BATCH" 2>/dev/null || echo "(未設)"; }

cmd_start() {
  local b=${1:-}
  [ -n "$b" ] || die "用法:$0 start <批次號>,例如 $0 start 0012"
  [[ $b =~ ^[0-9A-Za-z_-]+$ ]] || die "批次號只能用英數字、- 和 _:$b"

  mkdir -p "$RAPT_HOME"
  echo "$b" > "$RAPT_HOME/CURRENT_BATCH"
  echo "✓ 批次設為 $b"

  local tok; tok=$(token)
  [ -n "$tok" ] || die "unit 裡找不到 RAPT_PATH"

  systemctl --user start "$UNIT"
  # is-active 會在 socket 綁好之前就回 active,所以用健康檢查等,不用 is-active
  local up=0 i
  for i in $(seq 1 20); do
    curl -fsS -m 2 "http://127.0.0.1:$LOCAL_PORT/$tok" >/dev/null 2>&1 && { up=1; break; }
    sleep 0.5
  done
  [ "$up" = 1 ] || die "接收器沒回應(服務留著沒關,看 systemctl --user status $UNIT)"
  systemctl --user enable "$UNIT" >/dev/null
  echo "✓ 接收器 active(開機自動啟動已開)"

  sudo tailscale funnel --bg --https="$FUNNEL_PORT" "http://127.0.0.1:$LOCAL_PORT" >/dev/null
  echo "✓ Funnel 開啟(公網只通 POST)"

  local host; host=$(dnsname)
  echo
  echo "貼到 RAPT 後台 Data Streams → Custom:"
  echo "    https://$host:$FUNNEL_PORT/$tok"
  echo "手機看曲線圖(要開 Tailscale,不走公網):"
  echo "    http://$host:$LOCAL_PORT/$tok/chart"
  echo
  echo "網址貼好後回來跑:$0 status —— 看第一筆有沒有進來"
}

cmd_status() {
  local b tok n last act en fun
  b=$(batch); tok=$(token)
  act=$(systemctl --user is-active "$UNIT" 2>/dev/null || true)
  en=$(systemctl --user is-enabled "$UNIT" 2>/dev/null || true)
  fun=$(tailscale funnel status 2>/dev/null | head -1 || true)
  echo "批次      : $b"
  echo "接收器    : ${act:-unknown} / 開機啟動 ${en:-disabled}"
  echo "公網      : ${fun:-unknown}"
  local csv="$RAPT_HOME/rapt-data/$b/readings.csv"
  if [ -s "$csv" ]; then
    n=$(( $(wc -l < "$csv") - 1 )); last=$(tail -1 "$csv")
    echo "筆數      : $n"
    echo "最新一筆  : $last"
  else
    echo "筆數      : 0(還沒有資料)"
  fi
  if [ -n "$tok" ]; then echo "曲線圖    : http://$(dnsname):$LOCAL_PORT/$tok/chart"; fi
}

cmd_stop() {
  sudo tailscale funnel reset && echo "✓ Funnel 關閉(公網歸零)"
  systemctl --user disable --now "$UNIT" 2>/dev/null || true
  echo "✓ 接收器停止,批次 $(batch) 的資料留在 $RAPT_HOME/rapt-data/"
  echo "  記得把數據寫回 tommy_home_brewing.ods 結案"
}

case "${1:-}" in
  start)  shift; cmd_start "$@" ;;
  status) cmd_status ;;
  stop)   cmd_stop ;;
  *) echo "用法:$0 {start <批次號>|status|stop}" >&2; exit 1 ;;
esac
