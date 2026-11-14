# Oyan

Oyan is a screen-aware AI tutor for macOS that lives next to your cursor.
You ask about what is on your screen, by typing, by voice, or by circling it
with your own pen; Oyan looks at a screenshot, glides to the relevant spot,
and writes and draws its explanation right there in a handwriting style.

> **Status: versions 1 to 3 are done; version 4 (voice) is in progress.** See
> [Updates](#updates) for what works so far.

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
   with `python -m oyan --log`.
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
- **Microphone**, only if you ask by voice: macOS asks the first time.
- **Screen Recording**, for the screenshot: System Settings > Privacy &
  Security > Screen & System Audio Recording, switch on the same app, then
  restart Oyan.

## Updates

**1. The overlay.** Oyan is a small orange dot that glides after the cursor.
It sits in a see-through window on top of everything, and clicks pass straight
through it.

![Oyan as an orange dot next to the cursor](docs/oyan-dot.png)

**2. The hotkey and the ask box.** Press **Option + A** in any
app and a small text box opens next to the cursor. Enter sends the question,
Esc closes the box, and you are returned to the app you were in.

**3. The screenshot.** When you press Enter, and only then, Oyan takes one
picture of the screen your cursor is on. The only copy kept is the one in
the "what left my Mac" log (see update 10), which stays on your Mac.

**4. Asking the AI.** The question and the screenshot go to the AI model, and
the answer comes back with a position on the screen. Oyan does this by running
the `claude` command-line program (Claude Code) that you have installed and
signed in to, so Oyan itself never handles a password. The dot pulses while it
waits. The AI is given no tools: it cannot read files, run commands or browse,
so text hidden in a screenshot cannot trick it into doing anything but answer.

**5. Pointing and handwriting.** The dot flies along a curved path to the spot
the answer is about, drops a small marker there, and writes the answer beside
it, letter by letter, on a little piece of paper.

**6. The board.** Answers stay on screen like writing on a school board, up
to three at a time; a fourth pushes the oldest off. Each new answer is placed
where it covers no other answer or drawing. Under the newest one a small box
waits for your next question: click in it (or press the hotkey) and type. To
erase, rub the cursor quickly over an answer, like a cloth: a strip is rubbed
out where the cursor went, and when most of the answer is gone the rest goes
too. Moving the cursor slowly does nothing. Esc wipes the whole board.

**7. Circles, underlines and arrows.** The AI can now ask for a thing to be
circled, a piece of text underlined, or an arrow drawn. The dot draws them
live with a red marker, a little wobbly on purpose so they look hand-drawn,
and they are wiped together with the answer they belong to.

**8. Idle sketches.** Leave the mouse still for half a minute and the dot
wanders to the bottom-right corner and draws a small chalk doodle (a cat, a
rocket, a sun and seven others), admires it for a few seconds, and lets it
fade. Move the mouse and it comes straight back. The doodles are built into
the program: no AI call, no screenshot, nothing sent.

**9. Region select.** Send a question with **Shift+Enter** instead of Enter
and the screen dims: drag a box over the part you want Oyan to look at. Only
that rectangle is captured and sent. Esc cancels and sends nothing.

**10. "What left my Mac" log.** Before anything is sent, Oyan writes it
down: the exact picture, the exact words, the time, and where it went. If the
note cannot be written, nothing is sent. See it all on one page, or delete it:

```bash
python -m oyan --log          # open the list in your browser
python -m oyan --clear-log    # delete the whole record
```

The record lives in `~/.oyan/sent`, readable only by your Mac user account,
and keeps the newest 200 requests.

**11. Blocked apps.** Oyan refuses to take a screenshot while a password
manager (1Password, Bitwarden, Keychain Access, Passwords and others) has a
window on screen. No picture is taken and nothing is sent; Oyan writes why.
The list is yours to edit:

```bash
python -m oyan --blocked              # show the list
python -m oyan --block "App Name"     # add an app
python -m oyan --unblock "App Name"   # remove one
```

A bank's website inside a browser cannot be recognised this way; use
Shift+Enter to send only part of the screen instead.

**12. Follow-up questions.** Oyan remembers the conversation: the earlier
questions and answers are sent along with each new question, so "and the
other one?" works. Every question still takes a fresh screenshot, so Oyan
always sees what is on your screen now, in whichever app you are. Wiping the
board with Esc also forgets the conversation.

**13. History.** Every question and its answer is kept in a plain file on
your Mac, so you can find something again:

```bash
python -m oyan --history             # open a page with a search box
python -m oyan --history save file   # print the entries containing those words
python -m oyan --clear-history       # delete the history
```

**14. Step-by-step mode.** Ask how to do something that takes several
clicks and Oyan answers one step at a time: it circles where to click, writes
"Step 1 of 4: ...", and waits. Click the circled spot and it moves on to the
next step. Esc stops. All steps are planned from the one picture you sent;
Oyan does not take new screenshots as you click, so a step hidden inside a
closed menu is given in words only.

**15. Freehand drawing.** Ask Oyan to draw something ("draw a cat") and it
sketches it on your screen with real pen strokes, part by part, instead of
just a circle. The idle doodles are also sturdier: a small wobble of the
mouse no longer stops one half-drawn.

**16. Spoken answers.** Oyan can read its answers aloud with the voice built
into macOS, entirely on your Mac. It is off by default; turn it on with
`python -m oyan --voice on` (or `auto` to speak only when you asked by
voice). Esc stops it mid-sentence.

**17. Asking by voice.** Press **Option + S**, speak, and press it
again. Oyan turns red while the microphone is on. A speech-recognition model
(Whisper) running on your Mac turns what you said into text, and the question
is sent at once with a fresh screenshot, as if you had typed it and pressed
Enter. Your voice never leaves the Mac. One-time setup:

```bash
python -m oyan --setup-voice    # downloads the model, about 150 MB, once
```

macOS will ask for Microphone permission for the app you start Oyan from.

**18. Faster answers.** The picture is now sent as a much smaller file, the
AI program is started while you are still typing, the answer is written
before the circles and arrows are drawn, and the animations are quicker.
An answer takes about four seconds from Enter to fully written.

**19. A new look.** Oyan is now a small triangle with a soft shadow, like
the tip of a mouse arrow, in burgundy or royal green. Type `/green` or `/burgundy` in the ask
box to switch; the choice is remembered.

**20. Your own pen.** Hold **Option + D** and drag to draw on the
screen: circle a piece of code, underline a word, point an arrow. Let go of
the keys and the ask box opens next to your drawing. Your blue marks are in
the screenshot, so the AI sees exactly what you mean. They disappear when
the answer arrives.

**21. A tutor, not an answer machine.** Show Oyan an exercise (maths,
physics, code) and ask for help: it gives one concrete next step for that
exact exercise, not the final answer. Show it your attempt and it tells you
whether it is right and where the first mistake is. Say "show me the
solution" when you want the whole thing. For problems that are easier to see
than to read, it draws a small labelled sketch, such as two cars on a road
with their speeds and the gap between them.

**22. Easy keys.** Three neighbouring keys under the left hand, each with
Option: **Option + A** to Ask, **Option + S** to Speak, hold **Option + D**
to Draw. Oyan now takes these keys for itself, so they no longer type odd
characters into the app you are in or switch the keyboard language.

## Credits

Oyan is inspired by [Clicky](https://github.com/farzaa/clicky) by Farza (MIT
licence). Oyan is written from scratch in Python and shares no code with it.

## Licence

MIT. See [LICENSE](LICENSE).
