[app]
title = LPTest
package.name = lptest
package.domain = org.lptest

icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png
presplash.color = #05020c

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,wav,mp3,ogg,json,txt

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
# IMPORTANT -- reportlab: python-for-android's bundled "reportlab"
# recipe tries to compile reportlab's optional C accelerators, which
# is fundamentally broken under Python 3.11+ (confirmed upstream bug,
# kivy/python-for-android#2782). p4a.blacklist_requirements below is
# documented as p4a's own way to skip a recipe -- but buildozer 1.5.0
# silently drops it instead of passing it to p4a (confirmed: absent
# from the actual executed command in CI logs), so it's kept here as a
# harmless no-op in case a future buildozer version honors it. The fix
# that actually works is in build-apk.yml: it deletes this recipe
# directly from buildozer's own isolated python-for-android clone
# (.buildozer/android/platform/python-for-android/), which is the copy
# actually used -- don't remove that step without something else in
# its place, or this starts failing the same way again.
p4a.blacklist_requirements = reportlab
#
# python3/hostpython3 MUST stay pinned to the same exact version, or the
# build fails immediately with "python3 should have same version as
# hostpython3". Unpinned "python3" resolves to whatever the newest
# available release is (e.g. 3.14), which breaks other things too.
#
# IMPORTANT -- pillow is included here because of the reportlab fix
# above: with reportlab's recipe blacklisted, it installs as a plain
# pip package instead, and its optional image-handling needs Pillow
# available directly rather than picking it up implicitly the way the
# recipe build did. This mirrors the community-confirmed working fix in
# kivy/python-for-android#2782.
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.1,pypdf,plyer,pyjnius,reportlab,pillow,requests

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
