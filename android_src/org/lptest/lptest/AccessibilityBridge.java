package org.lptest.lptest;

import android.content.Context;
import android.graphics.Rect;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.view.ViewCompat;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import androidx.customview.widget.ExploreByTouchHelper;

import java.util.List;

/**
 * Kivy draws its entire UI on one OpenGL surface, so there are no real
 * Android View objects (Button, TextView, ...) for TalkBack to inspect.
 * This is a transparent overlay, sized to fill the whole window, that
 * sits on top of that surface and answers TalkBack's questions --
 * "what's on screen?", "what's currently focused?", "the user
 * double-tapped, activate it" -- using a list of "virtual" nodes that
 * the Python side (accessibility_bridge.py / VoiceNavMixin in main.py)
 * keeps in sync with whatever is currently visible.
 *
 * It does not intercept normal touches: ExploreByTouchHelper only takes
 * over input while Android's touch-exploration mode (TalkBack) is
 * active. With TalkBack off, taps/swipes pass straight through to the
 * Kivy surface underneath as before.
 */
public class AccessibilityBridge extends View {

    /** One focusable/announceable element, mirroring VoiceNavMixin's _voice_nav_items. */
    public static class Node {
        final String label;
        final Rect bounds; // local (view) pixel coordinates, top-left origin
        final boolean clickable;

        public Node(String label, int left, int top, int right, int bottom, boolean clickable) {
            this.label = label;
            this.bounds = new Rect(left, top, right, bottom);
            this.clickable = clickable;
        }
    }

    /** Implemented from Python (pyjnius PythonJavaClass) and set via setClickListener(). */
    public interface ClickListener {
        void onNodeClicked(int index);
    }

    private static AccessibilityBridge instance;

    private final java.util.List<Node> nodes = new java.util.ArrayList<>();
    private final Helper helper;
    private ClickListener clickListener;

    public AccessibilityBridge(Context context) {
        super(context);
        helper = new Helper(this);
        ViewCompat.setAccessibilityDelegate(this, helper);
        setFocusable(true);
        setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_YES);
        setBackgroundColor(0x00000000); // fully transparent, purely a bridge
        instance = this;
    }

    public static AccessibilityBridge getInstance() {
        return instance;
    }

    // ---- called from Python, main/UI thread only ----

    public void setNodes(List<Node> newNodes) {
        nodes.clear();
        if (newNodes != null) nodes.addAll(newNodes);
        helper.invalidateRoot();
    }

    public void setFocusedIndex(int index) {
        if (index >= 0 && index < nodes.size()) {
            helper.sendEventForVirtualView(index, AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED);
        }
    }

    public void announceClick(int index) {
        if (index >= 0 && index < nodes.size()) {
            helper.sendEventForVirtualView(index, AccessibilityEvent.TYPE_VIEW_CLICKED);
        }
    }

    public void setClickListener(ClickListener listener) {
        this.clickListener = listener;
    }

    // ---- plumbing so touch-exploration hover/key events actually reach the helper ----

    @Override
    public boolean dispatchHoverEvent(MotionEvent event) {
        if (helper.dispatchHoverEvent(event)) {
            return true;
        }
        return super.dispatchHoverEvent(event);
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        if (helper.dispatchKeyEvent(event)) {
            return true;
        }
        return super.dispatchKeyEvent(event);
    }

    @Override
    protected void onFocusChanged(boolean gainFocus, int direction, @Nullable Rect previouslyFocusedRect) {
        super.onFocusChanged(gainFocus, direction, previouslyFocusedRect);
        helper.onFocusChanged(gainFocus, direction, previouslyFocusedRect);
    }

    private class Helper extends ExploreByTouchHelper {
        Helper(@NonNull View host) {
            super(host);
        }

        @Override
        protected int getVirtualViewAt(float x, float y) {
            for (int i = 0; i < nodes.size(); i++) {
                if (nodes.get(i).bounds.contains((int) x, (int) y)) return i;
            }
            return ExploreByTouchHelper.HOST_ID;
        }

        @Override
        protected void getVisibleVirtualViews(List<Integer> virtualViewIds) {
            for (int i = 0; i < nodes.size(); i++) virtualViewIds.add(i);
        }

        @Override
        protected void onPopulateNodeForVirtualView(int virtualViewId, @NonNull AccessibilityNodeInfoCompat node) {
            if (virtualViewId < 0 || virtualViewId >= nodes.size()) {
                node.setContentDescription("");
                node.setBoundsInParent(new Rect(0, 0, 1, 1));
                return;
            }
            Node n = nodes.get(virtualViewId);
            node.setContentDescription(n.label);
            node.setBoundsInParent(n.bounds);
            node.setClassName("android.widget.Button");
            node.setClickable(n.clickable);
            node.setFocusable(true);
            node.setEnabled(true);
            node.setVisibleToUser(true);
            if (n.clickable) {
                node.addAction(AccessibilityNodeInfoCompat.AccessibilityActionCompat.ACTION_CLICK);
            }
        }

        @Override
        protected boolean onPerformActionForVirtualView(int virtualViewId, int action, @Nullable Bundle arguments) {
            if (action == AccessibilityNodeInfo.ACTION_CLICK) {
                if (clickListener != null) {
                    clickListener.onNodeClicked(virtualViewId);
                    return true;
                }
            }
            return false;
        }
    }
}
