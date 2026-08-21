// 허브 방문·클릭 카운터 (Cloudflare Worker, 2026-08-14 디렉터 지시
//  — "몇 명이나 들어왔는지, 각 상품 링크 클릭 얼마나 했는지. 나만 볼 수 있게, 내 방문은 빼고")
// 경로:
//   /px?me=0|1        방문 비콘 (me=1은 디렉터 — 카운트 제외)
//   /go?n=<슬러그>&u=<쿠팡URL>&me=0|1   클릭 카운트 후 302 리다이렉트 (쿠팡 도메인만 허용)
//   /stats?k=<키>     집계 JSON (키는 keys.env의 HUB_STATS_KEY — 봇의 '허브' 명령이 조회)
// 날짜는 KST 기준. KV 증가는 비원자적이지만 이 트래픽 규모에선 충분하다.
export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const day = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
    const bump = async (k) => {
      const v = parseInt((await env.KV.get(k)) || "0", 10) + 1;
      await env.KV.put(k, String(v));
    };
    if (url.pathname === "/px") {
      if (url.searchParams.get("me") !== "1") {
        await bump("view:total");
        await bump("view:" + day);
      }
      return new Response(null, { status: 204, headers: { "cache-control": "no-store" } });
    }
    if (url.pathname === "/go") {
      let dest;
      try {
        dest = new URL(url.searchParams.get("u") || "");
      } catch (e) {
        return new Response("bad url", { status: 400 });
      }
      if (dest.hostname !== "link.coupang.com" && dest.hostname !== "www.coupang.com") {
        return new Response("forbidden", { status: 403 });   // 오픈 리다이렉트 방지 — 쿠팡만
      }
      const n = (url.searchParams.get("n") || "etc").slice(0, 48);
      if (url.searchParams.get("me") === "1") {
        await bump("me:click:" + n);   // 디렉터 테스트분 — 실적 집계에서 분리 (2026-08-16; 2026-08-21 slug 오타 수정 — 디렉터 기기에서만 500)
      } else {
        await bump("click:" + n);
        await bump("day:" + day + ":click:" + n);
      }
      return Response.redirect(dest.toString(), 302);
    }
    if (url.pathname === "/webhook") {
      // Instagram 댓글 웹훅 (2026-08-21 — 개발 모드에서 REST 댓글 읽기가 차단돼 푸시로 우회)
      if (req.method === "GET") {
        // Meta 구독 검증 핸드셰이크
        if (url.searchParams.get("hub.verify_token") === env.STATS_KEY) {
          return new Response(url.searchParams.get("hub.challenge") || "", { status: 200 });
        }
        return new Response("bad token", { status: 403 });
      }
      if (req.method === "POST") {
        let body;
        try { body = await req.json(); } catch (e) { return new Response("bad json", { status: 400 }); }
        try {
          for (const entry of body.entry || []) {
            for (const ch of entry.changes || []) {
              if (ch.field !== "comments") continue;
              const v = ch.value || {};
              if (!v.id) continue;
              await env.KV.put("whc:" + v.id, JSON.stringify({
                id: v.id, text: v.text || "",
                from: (v.from && v.from.username) || "", from_id: (v.from && v.from.id) || "",
                media: (v.media && v.media.id) || "", ts: Date.now()
              }), { expirationTtl: 604800 });
            }
          }
          for (const entry of body.entry || []) {
            for (const ms of entry.messaging || []) {
              if (!ms.message || ms.message.is_echo) continue;   // 우리가 보낸 메시지 에코는 제외
              const mid = ms.message.mid || (entry.id + "_" + ms.timestamp);
              await env.KV.put("whm:" + mid, JSON.stringify({
                type: "message", id: mid,
                from_id: (ms.sender && ms.sender.id) || "",
                text: (ms.message.text) || "",
                payload: (ms.message.quick_reply && ms.message.quick_reply.payload) || "",
                ts: ms.timestamp || Date.now()
              }), { expirationTtl: 604800 });
            }
          }
        } catch (e) { /* 이벤트 하나 깨져도 200 — Meta 재전송 폭주 방지 */ }
        return new Response("ok", { status: 200 });
      }
      return new Response("nope", { status: 405 });
    }
    if (url.pathname === "/events") {
      // 봇이 소비: 저장된 댓글 이벤트 반환 후 삭제
      if (url.searchParams.get("k") !== env.STATS_KEY) return new Response("forbidden", { status: 403 });
      const out = [];
      let page = await env.KV.list({ prefix: "whc:" });
      const page2 = await env.KV.list({ prefix: "whm:" });
      page = { keys: page.keys.concat(page2.keys) };
      for (const key of page.keys) {
        const v = await env.KV.get(key.name);
        if (v) out.push(JSON.parse(v));
        await env.KV.delete(key.name);
      }
      return new Response(JSON.stringify(out), { headers: { "content-type": "application/json" } });
    }
    if (url.pathname === "/reset") {
      // 오염 데이터 정리 (2026-08-16: 배포 당일 디렉터 테스트 클릭 9건이 실적으로 잡혀 있었다)
      if (url.searchParams.get("k") !== env.STATS_KEY) return new Response("nope", { status: 403 });
      const list = await env.KV.list();
      let n = 0;
      for (const key of list.keys) { await env.KV.delete(key.name); n++; }
      return new Response("reset " + n + " keys", { headers: { "content-type": "text/plain" } });
    }

    if (url.pathname === "/stats") {
      if (url.searchParams.get("k") !== env.STATS_KEY) {
        return new Response("forbidden", { status: 403 });
      }
      const out = {};
      let cursor;
      do {
        const page = await env.KV.list({ cursor });
        for (const key of page.keys) {
          out[key.name] = parseInt((await env.KV.get(key.name)) || "0", 10);
        }
        cursor = page.list_complete ? null : page.cursor;
      } while (cursor);
      if (url.searchParams.get("fmt") !== "html") {
        return new Response(JSON.stringify(out, null, 1),
          { headers: { "content-type": "application/json; charset=utf-8" } });
      }
      // 디렉터 북마크용 미니 대시보드 (2026-08-14 — "수시로 확인" 요청)
      const today = day;
      const views = Object.entries(out).filter(([k]) => k.startsWith("view:") && k !== "view:total")
        .sort((a, b) => b[0].localeCompare(a[0])).slice(0, 14);
      const clicks = Object.entries(out).filter(([k]) => k.startsWith("click:"))
        .sort((a, b) => b[1] - a[1]);
      const esc = (t) => t.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
      const rows = (arr, label) => arr.length
        ? arr.map(([k, v]) => `<tr><td>${esc(decodeURIComponent(k.split(":").slice(1).join(":")))}</td><td class="n">${v}</td></tr>`).join("")
        : `<tr><td colspan="2" class="dim">${label} 아직 없음</td></tr>`;
      const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>허브 집계</title><style>
body{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;background:#fff;color:#12192e;max-width:440px;margin:0 auto;padding:40px 20px}
h1{font-size:22px;font-weight:900}h1 span{color:#ffb43c}
.big{display:flex;gap:12px;margin:18px 0}
.card{flex:1;border:1px solid #e6e8eb;border-radius:14px;padding:14px 16px}
.card b{display:block;font-size:26px}.card i{font-style:normal;color:#8a8f98;font-size:12px}
h2{font-size:14px;color:#8a8f98;margin:22px 0 8px}
table{width:100%;border-collapse:collapse}td{padding:7px 4px;border-bottom:1px solid #f0f1f3;font-size:14px}
td.n{text-align:right;font-weight:700}.dim{color:#b3b8bf}
footer{color:#b3b8bf;font-size:11px;margin-top:28px}
</style></head><body>
<h1>1일 <span>1지식</span> · 허브 집계</h1>
<div class="big">
<div class="card"><i>오늘 방문</i><b>${out["view:" + today] || 0}</b></div>
<div class="card"><i>누적 방문</i><b>${out["view:total"] || 0}</b></div>
</div>
<h2>상품별 클릭 (누적)</h2><table>${rows(clicks.filter(([k]) => k.split(":").length === 2), "클릭")}</table>
<h2>일별 방문 (최근)</h2><table>${rows(views, "방문")}</table>
<footer>디렉터 기기(#me 등록분) 제외 집계 · 새로고침하면 갱신됩니다</footer>
</body></html>`;
      return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
    }
    return new Response("ok");
  },
};
