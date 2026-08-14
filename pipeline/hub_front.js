// 허브 프런트 (2026-08-14 디렉터: "유튜브 채널 메인에 URL로 뜬다" — r2.dev 긴 주소 대신
// hub.daily1know.workers.dev 로 노출되게 하는 예쁜 주소 워커. 내용은 R2 허브 페이지를 그대로 서빙)
const R2_HUB = "https://pub-ec2b8489848a41b69e3a0c3ed23c7060.r2.dev/hub/index.html";
export default {
  async fetch(req) {
    const r = await fetch(R2_HUB, { cf: { cacheTtl: 0 } });
    return new Response(r.body, {
      status: r.status,
      headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
    });
  },
};
