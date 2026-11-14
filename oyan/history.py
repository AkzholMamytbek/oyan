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
  body {{ font: 15px -apple-system, sans-serif; background: #fffaeb; color: #3c2814;
         max-width: 900px; margin: 40px auto; padding: 0 20px; }}
  h1 {{ font-size: 24px; }}
  input {{ font: inherit; width: 100%; box-sizing: border-box; padding: 10px 14px;
          border: 1.5px solid #3c2814; border-radius: 10px; background: white; }}
  article {{ display: flex; gap: 20px; padding: 18px 0; border-top: 1px solid #d9cdb4; }}
  img {{ width: 220px; border: 1px solid #3c2814; border-radius: 8px; display: block; }}
  time {{ color: #7a6a55; font-size: 13px; }}
  .question {{ font-weight: 600; margin: 6px 0; }}
  .answer {{ margin: 0; }}
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
