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
      if (url.searchParams.get("me") !== "1") {
        await bump("click:" + n);
        await bump("day:" + day + ":click:" + n);
      }
      return Response.redirect(dest.toString(), 302);
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
      return new Response(JSON.stringify(out, null, 1),
        { headers: { "content-type": "application/json; charset=utf-8" } });
    }
    return new Response("ok");
  },
};
