[app]
title = LPTest
package.name = lptest
package.domain = org.lptest

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,wav,mp3

version = 1.0

# Added "android" module and standard requirements
requirements = python3,kivy==2.3.1,pypdf,python-docx,plyer,pyjnius,android

orientation = portrait
fullscreen = 0

# Added necessary storage permissions for file parsing
android.permissions = INTERNET, VIBRATE, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE

android.minapi = 24
android.api = 34
android.ndk = 25b

android.archs = arm64-v8a, armeabi-v7a

log_level = 2
warn_on_root = 1

[buildozer]
log_level = 2
