# LPTest — Kivy / Android rebuild

This is a ground-up UI rewrite of the desktop LPTest, built on **Kivy**
instead of Tkinter, specifically so it has a real path to an Android
`.apk`. Tkinter has no Android backend at all, so the original app could
never be packaged for Android no matter what build tool was used — this
rebuild is what makes an APK possible.

## What's different from the desktop version

- **No NVDA/JAWS/SAPI screen-reader announcements, and no "Read Aloud"
  voice.** Those were Windows-only APIs (`accessible_output2`, `edge-tts`)
  with no Android equivalent — this was agreed as the tradeoff for going
  the Kivy route. Android has its own accessibility system (TalkBack),
  which would need a separate, Android-specific pass if you want that
  back later.
- **No native drag-and-drop.** File selection is a plain Kivy file
  browser (works the same on desktop and Android).
- The quiz logic, file parsing (PDF/DOCX/TXT), and question generation
  are the exact same `file_parser.py` / `question_generator.py` /
  `quiz_history.py` as the desktop app — none of that needed to change.
- The options list sits in a scrolling container, so — unlike the
  original cut-off bug — nothing can ever get clipped, on any screen
  size; it scrolls instead.

## Try it on your PC first (fastest way to test changes)

```
pip install -r requirements.txt
python main.py
```

This runs the *exact* app, just windowed on your desktop instead of on a
phone — the fastest way to check that a quiz loads and flows correctly
before waiting on a full Android build.

## Getting an actual `.apk`

Building an Android package means downloading and running Google's
Android SDK/NDK toolchain (multiple GB, plus Gradle) — that download
isn't reachable from this chat's sandboxed network, so the `.apk` itself
has to be built somewhere with normal internet access. Two easy ways:

### Option A — GitHub Actions (recommended, no setup on your machine)

1. Push this folder to a new GitHub repo.
2. The included `.github/workflows/build-apk.yml` builds it automatically
   on every push to `main` (or run it manually from the repo's **Actions**
   tab → "Build LPTest APK" → **Run workflow**).
3. When the run finishes (~15–25 minutes the first time), open it and
   download the `LPTest-debug-apk` artifact — that's your `.apk`.
4. Copy it to your phone and install it (you'll need to allow "install
   from unknown sources" the first time, same as any APK not from the
   Play Store).

### Option B — Build it yourself on a Linux machine / WSL

```
pip install buildozer cython
sudo apt install -y openjdk-17-jdk build-essential git unzip zip
buildozer android debug
```

The first run downloads the Android SDK/NDK automatically (this is the
slow part — expect 20–40 minutes and a few GB of downloads) and produces
`bin/lptest-1.0-debug.apk`.

## Known things worth testing on a real device before trusting this fully

- **File picking on Android 11+** uses scoped storage; the built-in Kivy
  file browser can read most user-visible files, but some device/OEM
  file-manager quirks are hard to fully predict without testing on
  actual hardware. If "Upload File" can't see a file you expect, try
  moving it to the Downloads folder first.
- `python-docx` depends on `lxml`, which has to be compiled for Android
  by python-for-android during the build — this is included in
  `buildozer.spec` already, but is the most likely single point of
  build failure if Android tooling versions drift over time. If the
  build fails specifically on `lxml`, that's the first place to look.
- Font/button sizing was verified in a desktop Kivy run (headless, via
  Xvfb) with both short and long answer options, and correctly avoided
  any cut-off — but exact spacing should still get a quick look on a
  real phone screen since that's the actual target device.
