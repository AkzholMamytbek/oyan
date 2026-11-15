"""History: every question you asked and the answer you got, kept on this Mac.

The file is ~/.oyan/history/history.jsonl, one line of JSON per question.
It is plain text, readable only by your Mac user account, never uploaded.

    python -m oyan --history            open a page with a search box
    python -m oyan --history save file  print the entries containing those words
    python -m oyan --clear-history      delete the history

How this differs from the "what left my Mac" log (sent_log.py): the log
records what was SENT, exactly, as a privacy check. The history records the
question together with the ANSWER, so you can find something again.
"""

import html
import json
import shutil
import subprocess
from datetime import datetime

from oyan.capture import DATA_FOLDER

HISTORY_FOLDER = DATA_FOLDER / "history"
HISTORY_FILE = HISTORY_FOLDER / "history.jsonl"
PAGE_FILE = HISTORY_FOLDER / "index.html"


def record(question, answer, picture_name, follow_up):
    """Add one question and its answer."""
    HISTORY_FOLDER.mkdir(parents=True, exist_ok=True)
    HISTORY_FOLDER.chmod(0o700)   # 700 = only your Mac user account may open it
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "question": question,
        "answer": answer,
        "picture": picture_name,   # the file name of the picture in the sent log
        "follow_up": follow_up,    # True if it was asked about the previous picture
    }
    with open(HISTORY_FILE, "a") as file:
        file.write(json.dumps(entry) + "\n")
    HISTORY_FILE.chmod(0o600)


def read_entries():
    """All entries, oldest first."""
    if not HISTORY_FILE.exists():
        return []
    entries = []
    for line in HISTORY_FILE.read_text().splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass   # skip a damaged line rather than fail
    return entries


def search(words):
    """Entries whose question or answer contains ALL the given words."""
    words = [word.lower() for word in words]
    found = []
    for entry in read_entries():
        haystack = (entry["question"] + " " + entry["answer"]).lower()
        if all(word in haystack for word in words):
            found.append(entry)
    return found


def clear():
    """Delete the history. Returns how many entries were removed."""
    count = len(read_entries())
    if HISTORY_FOLDER.exists():
        shutil.rmtree(HISTORY_FOLDER)
    return count


def build_page():
    """Write index.html (with a search box) and return its path."""
    HISTORY_FOLDER.mkdir(parents=True, exist_ok=True)
    HISTORY_FOLDER.chmod(0o700)
    entries = read_entries()

    cards = []
    for entry in reversed(entries):   # newest first
        # The picture lives in the sent log's folder, next to this one. It may
        # be gone if the log was cleared; then the page shows no picture.
        picture = ""
        if entry.get("picture") and (DATA_FOLDER / "sent" / entry["picture"]).exists():
            link = "../sent/" + html.escape(entry["picture"])
            picture = f'<a href="{link}"><img src="{link}" alt="The picture this was about"></a>'
        label = " (follow-up)" if entry.get("follow_up") else ""
        cards.append(f"""
    <article>
      {picture}
      <div>
        <time>{html.escape(entry["time"])}{label}</time>
        <p class="question">{html.escape(entry["question"])}</p>
        <p class="answer">{html.escape(entry["answer"])}</p>
      </div>
    </article>""")

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Oyan: history</title>
<style>
  :root {{ color-scheme: light dark; --text: #1d1d1f; --quiet: #6e6e73; --back: #f5f5f7;
           --card: #ffffff; --line: rgba(0, 0, 0, 0.08); --accent: #0071e3; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --text: #f5f5f7; --quiet: #a1a1a6; --back: #000000;
             --card: #1c1c1e; --line: rgba(255, 255, 255, 0.12); --accent: #2997ff; }}
  }}
  body {{ font: 15px/1.5 -apple-system, "SF Pro Text", sans-serif; background: var(--back); color: var(--text);
         max-width: 860px; margin: 56px auto; padding: 0 20px; -webkit-font-smoothing: antialiased; }}
  h1 {{ font-size: 34px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 6px; }}
  p {{ color: var(--quiet); }}
  article {{ display: flex; gap: 20px; padding: 18px; margin: 14px 0; background: var(--card);
            border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 8px 28px rgba(0, 0, 0, 0.06); }}
  img {{ border: 1px solid var(--line); border-radius: 10px; display: block; }}
  code {{ font: 13px ui-monospace, "SF Mono", monospace; }}
  input {{ font: inherit; width: 100%; box-sizing: border-box; padding: 11px 16px; margin: 8px 0;
          color: var(--text); background: var(--card); border: 1px solid var(--line);
          border-radius: 12px; outline: none; }}
  input:focus {{ border-color: var(--accent); box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 25%, transparent); }}
  img {{ width: 220px; }}
  time {{ color: var(--quiet); font-size: 13px; }}
  .question {{ font-weight: 600; margin: 6px 0; color: var(--text); }}
  .answer {{ margin: 0; color: var(--text); }}
</style>
</head>
<body>
<h1>History</h1>
<p>{len(entries)} question(s), newest first. Stored only on this Mac.</p>
<input id="search" type="search" placeholder="Search questions and answers…" autofocus>
<div id="list">{"".join(cards) if cards else "<p>Nothing asked yet.</p>"}</div>
<script>
  // Hide every entry that does not contain all the words typed in the box.
  const box = document.getElementById("search");
  box.addEventListener("input", () => {{
    const words = box.value.toLowerCase().split(/\\s+/).filter(Boolean);
    for (const card of document.querySelectorAll("article")) {{
      const text = card.textContent.toLowerCase();
      card.style.display = words.every(word => text.includes(word)) ? "" : "none";
    }}
  }});
</script>
</body>
</html>
"""
    PAGE_FILE.write_text(page)
    PAGE_FILE.chmod(0o600)
    return PAGE_FILE


def open_page():
    """Build the page and open it in the default browser."""
    path = build_page()
    subprocess.run(["/usr/bin/open", str(path)], check=False)
    return path
