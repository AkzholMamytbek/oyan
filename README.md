# Oyan

Oyan is a screen-aware AI buddy for macOS that lives next to your cursor.
You ask a question about what is on your screen; Oyan looks at a screenshot,
glides to the relevant spot, and writes the answer right there in a
handwriting style.

> **Status: version 1 is being tested.** See [Updates](#updates) for what
> works so far.

## What makes Oyan different

- **It draws.** Answers are written beside the thing you asked about. It can
  circle, underline and draw arrows.
- **Every move is live.** Oyan glides along a curved path and draws stroke by
  stroke, so you can see where it is going.
- **Idle sketches.** When not in use, it doodles small funny things in a corner.

## Privacy rules

1. **Everything is local except the call to the AI model (Claude).** No other cloud service,
   no analytics, no remote key proxy.
2. **Capture only when asked.** A screenshot is taken only when you press the
   hotkey. Oyan never captures in the background.
3. **Idle sketches use no AI calls.** They come from a built-in set of doodles.
4. **Everything sent to the AI model is recorded** in a local log you can open
   (from version 2).
5. History, settings and logs are plain files in your home folder. They are
   never uploaded.

## Install and run

You need a Mac, Python 3.10 or newer, and
[Claude Code](https://code.claude.com/docs/en/setup) installed and signed in.

```bash
git clone https://github.com/AkzholMamytbek/oyan.git
cd oyan
python3 -m venv .venv              # create a private Python environment
source .venv/bin/activate          # switch this Terminal window to it
pip install -r requirements.txt    # install the packages Oyan needs
python -m oyan                     # start Oyan
```

Press `Ctrl+C` in the Terminal window to quit.

### Optional: use an API key instead

If you do not use Claude Code, Oyan can call the Anthropic API with your own
key. Run this and paste the key when asked (it is not shown as you paste):

```bash
python -m oyan --set-key       # save a key
python -m oyan --remove-key    # delete it again
```

The key is stored only on your Mac, in `~/.oyan/settings.json`, readable by
your user account alone. It is outside the project folder, so it can never
end up on GitHub.

### Permissions

macOS asks before a program may listen for a hotkey or look at the screen. The
permissions go to the app you start Oyan from (Terminal or Visual Studio Code):

- **Accessibility**, for the hotkey: System Settings > Privacy & Security >
  Accessibility, switch on Terminal (or Visual Studio Code), then restart Oyan.
- **Screen Recording**, for the screenshot: System Settings > Privacy &
  Security > Screen & System Audio Recording, switch on the same app, then
  restart Oyan.

## Updates

**1. The overlay.** Oyan is a small orange dot that glides after the cursor.
It sits in a see-through window on top of everything, and clicks pass straight
through it.

![Oyan as an orange dot next to the cursor](docs/oyan-dot.png)

**2. The hotkey and the ask box.** Press **Control + Option + Space** in any
app and a small text box opens next to the cursor. Enter sends the question,
Esc closes the box, and you are returned to the app you were in.

**3. The screenshot.** When you press Enter, and only then, Oyan takes one
picture of the screen your cursor is on. It is saved on your Mac as
`~/.oyan/last_screenshot.png` and replaced by the next one. Nothing is sent
anywhere yet.

**4. Asking the AI.** The question and the screenshot go to the AI model, and
the answer comes back with a position on the screen. Oyan does this by running
the `claude` command-line program (Claude Code) that you have installed and
signed in to, so Oyan itself never handles a password. The dot pulses while it
waits.

**5. Pointing and handwriting.** The dot flies along a curved path to the spot
the answer is about, drops a small marker there, and writes the answer beside
it, letter by letter, on a little piece of paper. Press Esc to clear it, or
the hotkey to ask something else.

## Credits

Oyan is inspired by [Clicky](https://github.com/farzaa/clicky) by Farza (MIT
licence). Oyan is written from scratch in Python and shares no code with it.

## Licence

MIT. See [LICENSE](LICENSE).
