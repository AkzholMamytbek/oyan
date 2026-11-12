# Oyan

Oyan is a screen-aware AI buddy for macOS that lives next to your cursor.
You ask a question about what is on your screen; Oyan looks at a screenshot,
glides to the relevant spot, and writes the answer right there in a
handwriting style.

> **Status: early work in progress.** Right now Oyan is only a small dot that
> follows the cursor. See the roadmap below for what is coming.

## What makes Oyan different

- **It draws.** Answers are written beside the thing you asked about. It can
  circle, underline and draw arrows.
- **Every move is live.** Oyan glides along a curved path and draws stroke by
  stroke, so you can see where it is going.
- **Idle sketches.** When not in use, it doodles small funny things in a corner.

## Privacy rules

1. **Everything is local except the call to the AI model.** No other cloud service,
   no analytics, no remote key proxy.
2. **Capture only when asked.** A screenshot is taken only when you press the
   hotkey. Oyan never captures in the background.
3. **Idle sketches use no AI calls.** They come from a built-in set of doodles.
4. **Everything sent to the AI model is recorded** in a local log you can open
   (from version 2).
5. History, settings and logs are plain files in your home folder. They are
   never uploaded.

## Install and run

You need a Mac and Python 3.10 or newer.

```bash
git clone https://github.com/AkzholMamytbek/oyan.git
cd oyan
python3 -m venv .venv              # create a private Python environment
source .venv/bin/activate          # switch this Terminal window to it
pip install -r requirements.txt    # install the packages Oyan needs
python -m oyan                     # start Oyan
```

Press `Ctrl+C` in the Terminal window to quit.

## Roadmap

**Version 1: the core loop**
- [x] Overlay window that follows the cursor
- [ ] Global hotkey opens a small text box near the cursor
- [ ] Take a screenshot when a question is asked
- [ ] Send screenshot and question to the AI model
- [ ] Glide to the spot the AI points at and write the answer beside it
- [ ] Esc dismisses

**Version 2: drawing and privacy**
- [ ] Circles, underlines and arrows
- [ ] Idle sketches
- [ ] Region select: only the part of the screen you drag over is sent
- [ ] "What left my Mac" log of every screenshot and question sent

**Version 3: smarter help**
- [ ] Step-by-step mode
- [ ] Follow-up questions on the same screenshot
- [ ] Local, searchable history
- [ ] Blocked apps (password managers, banking) with an editable list

**Version 4: voice, all local**
- [ ] Speech to text with a local Whisper model
- [ ] Spoken answers with the built-in macOS voice or a local voice model

## Credits

Oyan is inspired by [Clicky](https://github.com/farzaa/clicky) by Farza (MIT
licence). Oyan is written from scratch in Python and shares no code with it.

## Licence

MIT. See [LICENSE](LICENSE).
