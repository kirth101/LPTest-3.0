"""
Bridges VoiceNavMixin's on-screen focus items (main.py) to Android's real
accessibility framework -- TalkBack, Switch Access, Voice Access, etc --
through a transparent overlay View. See
android_src/org/lptest/lptest/AccessibilityBridge.java for the Java side.

Everything here is a safe no-op on non-Android platforms, or if the
overlay failed to attach for any reason (old device, missing androidx
dep, etc) -- the app's existing custom VoiceNavMixin swipe/TTS
navigation keeps working exactly as before either way.
"""
from kivy.utils import platform

_bridge = None            # the Java AccessibilityBridge instance
_click_listener = None    # keep a Python-side reference alive (pyjnius requirement)
_active_callbacks = []    # index -> python callable, rebuilt on every update_nodes()
_attached = False


def attach():
    """Create the overlay and add it on top of the Activity's content view.
    Call once, e.g. from LPTestApp.build() alongside _AndroidTTS._get_engine()."""
    global _bridge, _click_listener, _attached
    if platform != "android" or _attached:
        return
    try:
        from jnius import autoclass, PythonJavaClass, java_method
        from kivy.clock import Clock

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Bridge = autoclass("org.lptest.lptest.AccessibilityBridge")
        LayoutParams = autoclass("android.view.ViewGroup$LayoutParams")
        AndroidRContentId = autoclass("android.R$id").content

        activity = PythonActivity.mActivity
        _bridge = Bridge(activity)

        class ClickListener(PythonJavaClass):
            __javainterfaces__ = ["org/lptest/lptest/AccessibilityBridge$ClickListener"]
            __javacontext__ = "app"

            @java_method("(I)V")
            def onNodeClicked(self, index):
                # Called on the Android UI thread; hop back onto Kivy's
                # own clock/thread before touching any Kivy widgets.
                Clock.schedule_once(lambda *_a: _dispatch_click(index), 0)

        _click_listener = ClickListener()
        _bridge.setClickListener(_click_listener)

        def _add_overlay(*_a):
            content = activity.getWindow().getDecorView().findViewById(AndroidRContentId)
            lp = LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT)
            content.addView(_bridge, lp)

        Clock.schedule_once(_add_overlay, 0)
        _attached = True
    except Exception as e:
        print(f"LPTest: accessibility bridge attach failed: {e}")


def _dispatch_click(index):
    if 0 <= index < len(_active_callbacks):
        cb = _active_callbacks[index]
        if cb:
            cb()


def kivy_widget_to_android_rect(widget):
    """Convert a Kivy widget's on-screen box (window coords, origin
    bottom-left) into Android View pixel coords (origin top-left)."""
    from kivy.core.window import Window
    x1, y1 = widget.to_window(widget.x, widget.y)
    x2, y2 = widget.to_window(widget.right, widget.top)
    left, right = int(min(x1, x2)), int(max(x1, x2))
    top = int(Window.height - max(y1, y2))
    bottom = int(Window.height - min(y1, y2))
    return left, top, right, bottom


def update_nodes(items):
    """items: VoiceNavMixin._voice_nav_items -- list of (label, callback, widget)."""
    global _active_callbacks
    if platform != "android" or _bridge is None:
        return
    try:
        from jnius import autoclass
        ArrayList = autoclass("java.util.ArrayList")
        Node = autoclass("org.lptest.lptest.AccessibilityBridge$Node")

        _active_callbacks = [cb for (_label, cb, _widget) in items]
        java_nodes = ArrayList()
        for label, _callback, widget in items:
            if widget is None:
                continue
            left, top, right, bottom = kivy_widget_to_android_rect(widget)
            java_nodes.add(Node(str(label), left, top, right, bottom, True))
        _bridge.setNodes(java_nodes)
    except Exception as e:
        print(f"LPTest: accessibility bridge update_nodes failed: {e}")


def set_focus(index):
    if platform != "android" or _bridge is None:
        return
    try:
        _bridge.setFocusedIndex(index)
    except Exception as e:
        print(f"LPTest: accessibility bridge set_focus failed: {e}")


def announce_click(index):
    if platform != "android" or _bridge is None:
        return
    try:
        _bridge.announceClick(index)
    except Exception as e:
        print(f"LPTest: accessibility bridge announce_click failed: {e}")
