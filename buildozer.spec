[app]
title = LPTest
package.name = lptest
package.domain = org.lptest

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,wav,mp3

version = 1.0

# python-for-android pip package requirements needed on-device.
# Inisama ang pyjnius para sa direct Android Native Access (TTS Engines & Haptic Vibration)
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.1,pypdf,plyer,pyjnius

orientation = portrait
fullscreen = 0

# VIBRATE: haptic feedback on the swipe/double-tap accessibility gestures.
android.permissions = INTERNET, VIBRATE

android.minapi = 24
android.api = 34
android.ndk = 25b

android.archs = arm64-v8a, armeabi-v7a

log_level = 2
warn_on_root = 1

[buildozer]
log_level = 2
