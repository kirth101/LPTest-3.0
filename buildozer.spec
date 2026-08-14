[app]
title = LPTest
package.name = lptest
package.domain = org.lptest

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,wav,mp3,json,txt

version = 1.0

# python-for-android pip package requirements.
# IMPORTANT -- do not add python-docx or lxml back here: file_parser.py
# reads .docx files using only the Python standard library (zipfile +
# xml.etree.ElementTree) specifically to avoid lxml, whose Android build
# recipe is broken (a real multi-day debugging saga -- see git history/
# chat log if this gets reintroduced and breaks the build again).
#
# IMPORTANT -- do not add google-generativeai or google-genai here either:
# question_generator.py's Gemini integration calls Google's REST API
# directly via `requests` (already listed below) instead of either SDK.
# `google-generativeai` is permanently deprecated by Google (Nov 30,
# 2025) and no longer maintained; `google-genai`, the newer official
# SDK, would pull in a chain of new pip dependencies (httpx, pydantic,
# google-auth, websockets, ...) that have never been proven to
# cross-compile under python-for-android -- exactly the kind of fragile
# Android build risk this project already hit once with the freetype
# recipe. Calling the REST API over plain `requests` needs nothing new
# here at all.
#
# IMPORTANT -- reportlab: python-for-android's OWN bundled "reportlab"
# recipe tries to compile reportlab's optional C accelerators, which
# is fundamentally broken under Python 3.11+ (confirmed upstream bug,
# kivy/python-for-android#2782 -- PyFrameObject/struct _frame became
# opaque in CPython 3.11, and reportlab's old accelerator code still
# pokes at its previous internal layout). build-apk.yml was SUPPOSED
# to delete that bundled recipe before building so p4a falls back to
# a plain pip install (reportlab's own setup.py correctly treats
# those C accelerators as optional and skips a failed one rather than
# aborting the whole install, unlike p4a's dedicated recipe) -- but
# the 2026-08-14 CI log shows the build still going through
# .../other_builds/reportlab/.../rl_addons/rl_accel/_rl_accel.c,
# which is p4a's OWN recipe path, so that workflow step is evidently
# not taking effect (removed, reordered after the checkout it needs
# to run after, or the workflow file itself drifted). Until that's
# confirmed fixed, p4a.local_recipes below (pointing at
# ./p4a-recipes) is a belt-and-suspenders fix: it makes p4a prefer a
# same-named local recipe over its bundled broken one no matter what
# the workflow does, so this can't silently regress again. Do NOT
# remove p4a.local_recipes unless you've confirmed in a real CI log
# that reportlab is again installing as a plain pip package.
#
# python3/hostpython3 MUST stay pinned to the same exact version, or the
# build fails immediately with "python3 should have same version as
# hostpython3". Unpinned "python3" resolves to whatever the newest
# available release is (e.g. 3.14), which breaks other things too.
#
# IMPORTANT -- pillow is included here because of the reportlab fix
# above: with reportlab installing as a plain pip package instead of
# via a dedicated recipe, its optional image-handling needs Pillow
# available directly rather than picking it up implicitly the way the
# recipe build did. This mirrors the community-confirmed working fix
# in kivy/python-for-android#2782.
#
# reportlab is now pinned to 4.2.5 (a release confirmed to build
# cleanly under Python 3.11+) rather than left unpinned, since an
# unpinned pip install can silently resolve to whatever's newest and
# reintroduce edge cases. pillow/pyjnius are left unpinned: the
# "Could not find a version that satisfies ... Pillow==11.3.0" /
# "...pyjnius==1.7.0" errors in the same log were one-off PyPI index
# hiccups on GitHub's runner (both versions exist on PyPI, and the
# build proceeded past them on retry each time) rather than a real
# version problem, so pinning wouldn't have prevented them and isn't
# needed here.
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.1,pypdf,plyer,pyjnius,reportlab==4.2.5,pillow,requests

# Local recipe override directory -- see the reportlab comment above.
# Any recipe folder in here (e.g. p4a-recipes/reportlab/) takes
# priority over p4a's own bundled recipe of the same name.
p4a.local_recipes = %(source.dir)s/p4a-recipes

orientation = portrait
fullscreen = 0

# INTERNET: for the online quiz generator (Gemini, via requests) and
# checking for online questions. VIBRATE: haptic feedback on the
# swipe/double-tap accessibility gestures.
android.permissions = INTERNET, VIBRATE

android.minapi = 24
android.api = 34
android.ndk = 25b

android.archs = arm64-v8a, armeabi-v7a

log_level = 2
warn_on_root = 1

[buildozer]
log_level = 2
