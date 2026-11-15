"""The "what left my Mac" log.

Privacy rule: everything Oyan sends to the AI is written down here first, on
this Mac only, so you can always check what left it.

Where it is
-----------
The folder ~/.oyan/sent holds:
* log.jsonl  - one line per question, in JSON (time, the exact text sent,
               where it was sent, the model, and the picture's file name);
* one .jpg per question - an exact copy of the picture that was sent;
* index.html - a page listing all of it, rebuilt whenever you ask to see it.

The folder and its files can be read only by your own Mac user account, and
nothing in it is ever uploaded. Only the newest MAX_ENTRIES are kept.

    python -m oyan --log         open the page in your browser
    python -m oyan --clear-log   delete the whole log
"""

import html
import json
import shutil
import subprocess
from datetime import datetime

from oyan.capture import DATA_FOLDER

LOG_FOLDER = DATA_FOLDER / "sent"
LOG_FILE = LOG_FOLDER / "log.jsonl"
PAGE_FILE = LOG_FOLDER / "index.html"
MAX_ENTRIES = 200


def record(text, image_bytes, width, height, sent_via, model, system_prompt):
    """Write down one request. Called just before it is sent.

    Returns the file name of the saved picture."""
    LOG_FOLDER.mkdir(parents=True, exist_ok=True)
    LOG_FOLDER.chmod(0o700)   # 700 = only your Mac user account may open it

    now = datetime.now()
    picture_name = now.strftime("%Y-%m-%d_%H-%M-%S_%f") + ".jpg"
    picture_path = LOG_FOLDER / picture_name
    picture_path.write_bytes(image_bytes)
    picture_path.chmod(0o600)

    entry = {
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "text": text,                    # exactly the words that were sent
        "picture": picture_name,
        "picture_size": f"{width} x {height}",
        "sent_via": sent_via,
        "model": model,
        "instructions": system_prompt,   # the fixed instructions sent along
    }
    with open(LOG_FILE, "a") as file:
        file.write(json.dumps(entry) + "\n")
    LOG_FILE.chmod(0o600)

    _forget_oldest()
    return picture_name


def read_entries():
    """All entries, oldest first."""
    if not LOG_FILE.exists():
        return []
    entries = []
    for line in LOG_FILE.read_text().splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass   # skip a damaged line rather than fail
    return entries


def _forget_oldest():
    """Keep only the newest MAX_ENTRIES, deleting older lines and pictures."""
    entries = read_entries()
    if len(entries) <= MAX_ENTRIES:
        return
    for old in entries[:-MAX_ENTRIES]:
        (LOG_FOLDER / old["picture"]).unlink(missing_ok=True)
    with open(LOG_FILE, "w") as file:
        for entry in entries[-MAX_ENTRIES:]:
            file.write(json.dumps(entry) + "\n")


def clear():
    """Delete the whole log. Returns how many entries were removed."""
    count = len(read_entries())
    if LOG_FOLDER.exists():
        shutil.rmtree(LOG_FOLDER)
    return count


def build_page():
    """Write index.html from the log and return its path."""
    LOG_FOLDER.mkdir(parents=True, exist_ok=True)
    LOG_FOLDER.chmod(0o700)
    entries = read_entries()

    # html.escape makes text safe to put in a web page: a question containing
    # "<b>" is shown as those characters instead of being treated as code.
    cards = []
    for entry in reversed(entries):   # newest first
        picture = html.escape(entry["picture"])
        cards.append(f"""
    <article>
      <a href="{picture}"><img src="{picture}" alt="The picture that was sent"></a>
      <div>
        <time>{html.escape(entry["time"])}</time>
        <p class="text">{html.escape(entry["text"])}</p>
        <p class="meta">Picture: {html.escape(entry["picture_size"])} pixels<br>
        Sent through: {html.escape(entry["sent_via"])} (model: {html.escape(entry["model"])})</p>
        <details><summary>Fixed instructions sent along</summary>
        <p class="meta">{html.escape(entry.get("instructions", ""))}</p></details>
      </div>
    </article>""")

    if not cards:
        cards.append("<p>Nothing has been sent yet.</p>")

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Oyan: what left my Mac</title>
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
  img {{ width: 300px; }}
  time {{ font-weight: 600; color: var(--text); }}
  .text {{ white-space: pre-wrap; color: var(--text); }}
  .meta, summary {{ color: var(--quiet); font-size: 13px; }}
</style>
</head>
<body>
<h1>What left my Mac</h1>
<p>{len(entries)} request(s). Each one is a picture and a question that Oyan sent to the AI,
newest first. Click a picture to see it full size. These files are stored only on this Mac,
in <code>{html.escape(str(LOG_FOLDER))}</code>.</p>
{"".join(cards)}
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
