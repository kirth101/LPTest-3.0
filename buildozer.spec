[app]
title = LPTest
package.name = lptest
package.domain = org.lptest

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt

version = 1.0

# python-for-align/pip package requirements needed on-device.
# - kivy: the UI framework this app is built on
# - pypdf: PDF text extraction (file_parser.py)
# - python-docx (+ lxml): .docx text extraction (file_parser.py)
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.1,pypdf,plyer

orientation = portrait
fullscreen = 0

# Needed so the app can read a file the user picks (SAF-backed picks on
# Android 11+ don't require this, but requesting it keeps older devices
# and "browse a shared folder" style pickers working too).

# Reasonable modern floor/ceiling -- adjust upward over time as Google
# raises the minimum target API required for Play Store submissions.
android.minapi = 24
android.api = 34
android.ndk = 25b

android.archs = arm64-v8a, armeabi-v7a

log_level = 2
warn_on_root = 1

[buildozer]
log_level = 2
