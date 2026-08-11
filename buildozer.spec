[app]
title = LPTest
package.name = lptest
package.domain = org.lptest

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,wav,mp3

version = 1.0

# python-for-android pip package requirements needed on-device.
# - kivy: the UI framework this app is built on
# - pypdf: PDF text extraction (file_parser.py)
# - plyer: native Android file picker (SAF), text-to-speech, and haptic
#   vibration feedback for the spoken-navigation accessibility mode
#   (see main.py's speak() / VoiceNavMixin)
# (DOCX extraction uses only the Python standard library -- see
# file_parser.py -- specifically to avoid lxml, whose Android build
# recipe is broken against current NDK/Python versions.)
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.1,pypdf,plyer

orientation = portrait
fullscreen = 0

# VIBRATE: haptic feedback on the swipe/double-tap accessibility gestures.
# The file picker (Storage Access Framework) and text-to-speech need no
# runtime permission.
android.permissions = INTERNET, VIBRATE

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
