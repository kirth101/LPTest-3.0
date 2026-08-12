[app]
title = LPTest
package.name = lptest
package.domain = org.lptest

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,wav,mp3

version = 1.0

# python-for-android pip package requirements
requirements = python3,kivy==2.3.1,pypdf,python-docx,plyer,pyjnius

orientation = portrait
fullscreen = 0

# Android permissions for accessibility vibration
android.permissions = INTERNET, VIBRATE

android.minapi = 24
android.api = 34
android.ndk = 25b

android.archs = arm64-v8a, armeabi-v7a

log_level = 2
warn_on_root = 1

[buildozer]
log_level = 2
