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
# python3/hostpython3 MUST stay pinned to the same exact version, or the
# build fails immediately with "python3 should have same version as
# hostpython3". Unpinned "python3" resolves to whatever the newest
# available release is (e.g. 3.14), which breaks other things too.
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.1,pypdf,plyer,pyjnius,reportlab,requests,sh<2.0

orientation = portrait
fullscreen = 0

# INTERNET: for the online quiz generator. VIBRATE: haptic feedback on
# the swipe/double-tap accessibility gestures.
android.permissions = INTERNET, VIBRATE

android.minapi = 24
android.api = 34
android.ndk = 25b

android.archs = arm64-v8a, armeabi-v7a

log_level = 2
warn_on_root = 1

[buildozer]
log_level = 2
