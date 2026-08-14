#!/bin/bash
# 허브 카운터 Worker 배포 (2026-08-14) — 선행 조건: keys.env에 CLOUDFLARE_API_TOKEN
#   (권한: 계정 > Workers 스크립트:편집 + Workers KV 저장소:편집)
# 하는 일: KV 네임스페이스 생성 → Worker 업로드 → workers.dev 활성화 →
#          keys.env에 HUB_STATS_KEY/HUB_COUNTER_URL 기록 → 허브 재생성 + 봇 재시작
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

get_key() { { grep "^$1=" keys.env 2>/dev/null || true; } | head -1 | cut -d= -f2-; }   # 키 부재가 set -e를 죽이면 안 된다 (2026-08-14 실사고)
TOKEN="$(get_key CLOUDFLARE_API_TOKEN)"
ACC="$(get_key R2_ACCOUNT_ID)"
[[ -n "$TOKEN" ]] || { echo "keys.env에 CLOUDFLARE_API_TOKEN이 없습니다 — 토큰 생성 후 추가하세요" >&2; exit 3; }
[[ -n "$ACC" ]] || { echo "keys.env에 R2_ACCOUNT_ID 없음" >&2; exit 3; }
API="https://api.cloudflare.com/client/v4/accounts/$ACC"
AH="Authorization: Bearer $TOKEN"

echo "① KV 네임스페이스"
NSID=$(curl -sS -H "$AH" "$API/storage/kv/namespaces?per_page=100" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(next((n['id'] for n in d.get('result') or [] if n['title']=='hub-counter-kv'), ''))")
if [[ -z "$NSID" ]]; then
  NSID=$(curl -sS -X POST -H "$AH" -H "Content-Type: application/json" \
    -d '{"title":"hub-counter-kv"}' "$API/storage/kv/namespaces" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('success'), d; print(d['result']['id'])")
fi
echo "   NSID=$NSID"

STATS_KEY="$(get_key HUB_STATS_KEY)"
if [[ -z "$STATS_KEY" ]]; then
  STATS_KEY=$(openssl rand -hex 16)
  printf '\nHUB_STATS_KEY=%s\n' "$STATS_KEY" >> keys.env
fi

echo "② Worker 업로드"
META=$(python3 -c "
import json
print(json.dumps({'main_module':'hub_counter.js','compatibility_date':'2024-11-01',
 'bindings':[{'type':'kv_namespace','name':'KV','namespace_id':'$NSID'},
             {'type':'plain_text','name':'STATS_KEY','text':'$STATS_KEY'}]}))")
curl -sS -X PUT -H "$AH" "$API/workers/scripts/hub-counter" \
  -F "metadata=$META;type=application/json" \
  -F "hub_counter.js=@pipeline/hub_counter.js;type=application/javascript+module" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('success'), json.dumps(d.get('errors'), ensure_ascii=False); print('   업로드 OK')"

echo "③ workers.dev 서브도메인"
SUB=$(curl -sS -H "$AH" "$API/workers/subdomain" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print((d.get('result') or {}).get('subdomain') or '')")
if [[ -z "$SUB" ]]; then
  SUB="daily1know"
  curl -sS -X PUT -H "$AH" -H "Content-Type: application/json" \
    -d "{\"subdomain\":\"$SUB\"}" "$API/workers/subdomain" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('success'), json.dumps(d.get('errors'), ensure_ascii=False)"
fi
curl -sS -X POST -H "$AH" -H "Content-Type: application/json" \
  -d '{"enabled":true,"previews_enabled":false}' "$API/workers/scripts/hub-counter/subdomain" > /dev/null
URL="https://hub-counter.$SUB.workers.dev"
echo "   $URL"

if ! grep -q "^HUB_COUNTER_URL=" keys.env; then
  printf 'HUB_COUNTER_URL=%s\n' "$URL" >> keys.env
fi

echo "④ 동작 확인"
sleep 3
curl -sS -o /dev/null -w "   /px → %{http_code}\n" "$URL/px?me=1"
curl -sS "$URL/stats?k=$STATS_KEY" | head -3

echo "⑤ 허브 재생성(카운터 배선) + 봇 재시작"
.venv/bin/python3 -c "
import sys; sys.path.insert(0, 'pipeline')
import affiliate_bot as ab
items = ab.state().get('hub_items', [])
print('허브 갱신:', ab.update_hub(items))"
pm2 restart studio-affiliate > /dev/null && echo "   studio-affiliate 재시작 ✓"
echo "완료 — 텔레그램에 '허브'라고 보내면 집계가 옵니다. 디렉터 기기 제외 등록: 허브를 #me 붙여 한 번 열기"
