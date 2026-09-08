#!/usr/bin/env python3
"""텍스트 카드 게시 — make_cards.py 대신 사용 (2026-09-05 텍스트 시험용).
스레드에 publish_text로 게시하고, 블로그에 텍스트 글로 게시한다.

사���: CARD_MODE=1 .venv/bin/python3 pipeline/publish_text_card.py content/cards-*.json
"""
import json, os, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
os.chdir(ROOT)

def main():
    os.environ["CARD_MODE"] = "1"
    if len(sys.argv) < 2:
        sys.exit("사용: publish_text_card.py <cards.json>")
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        s = json.load(f)

    text = s.get("threads_text", "")
    if not text:
        sys.exit("threads_text가 없���")

    topic = s.get("topic", "")
    slug = os.path.splitext(os.path.basename(path))[0]

    # 1) 스레드 텍스트 게시
    from upload_threads import publish_text
    threads_url = publish_text(text)
    print(f"[threads] {threads_url}")

    # 2) 블로그 게시
    try:
        from upload_blogger import publish as blog_publish
        title = text.split("\n")[0]  # 첫 줄 = 제목
        # 본문을 HTML로 변환
        lines = text.strip().split("\n")
        html_parts = [f"<h2>{lines[0]}</h2>"]
        for line in lines[1:]:
            line = line.strip()
            if line:
                html_parts.append(f"<p>{line}</p>")
        html = "\n".join(html_parts)
        labels = ["테크", "카드"]
        blog_result = blog_publish(title, html, labels=labels, draft=False)
        blog_url = blog_result.get("url", "")
        print(f"[blog] {blog_url}")
    except Exception as e:
        print(f"[blog] 실패: {e}")
        blog_url = ""

    # 3) sent.log 기록
    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    log_line = f"{now} THTEXT:{slug}\n"
    with open(os.path.join(ROOT, "logs", "sent.log"), "a", encoding="utf-8") as f:
        f.write(log_line)

    # 4) topics_used.md 기록
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    hour = datetime.datetime.now().strftime("%H")
    entry = f"- {today} {hour}시 카드 [게시] {topic}\n"
    topics_path = os.path.join(ROOT, "content", "topics_used.md")
    with open(topics_path, "a", encoding="utf-8") as f:
        f.write(entry)

    print(f"[done] threads={threads_url} blog={blog_url}")

if __name__ == "__main__":
    main()
