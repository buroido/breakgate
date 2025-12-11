# xplatform_window.py
import sys
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QGuiApplication

def make_click_through(widget, on: bool, keep_topmost=True):
    """
    クロスプラットフォームで“クリック透過”ON/OFF。
    まず Qt 属性で実現。必要なら TopMost を維持。
    """
    widget.setAttribute(Qt.WA_TransparentForMouseEvents, on)
    f = widget.windowFlags()
    if on:
        f |= Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.Tool
        if keep_topmost:
            f |= Qt.WindowStaysOnTopHint
    else:
        f &= ~Qt.WindowTransparentForInput
        f &= ~Qt.FramelessWindowHint
        f &= ~Qt.Tool
        f |= Qt.Window
    widget.setWindowFlags(f)
    widget.show()  # 反映
    raise_topmost_noactivate(widget, True)


def raise_topmost_noactivate(widget, on=True):
    """
    “最前面”に押し上げ（フォーカスは奪わない）。
    まず Qt の raise_()、さらに OS ごとの SetWindowPos/NSWindow レベルを試す。
    """
    widget.raise_()

    if sys.platform.startswith("win"):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            SWP_NOMOVE=0x2; SWP_NOSIZE=0x1; SWP_NOACTIVATE=0x10; SWP_SHOWWINDOW=0x40
            HWND_TOPMOST=-1; HWND_NOTOPMOST=-2
            hwnd = int(widget.winId())
            user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST if on else HWND_NOTOPMOST,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
            )
        except Exception:
            pass

    elif sys.platform == "darwin":
        # AppKit があれば NSWindow レベルも上げる（無くても Qt だけで動く）
        try:
            from AppKit import NSApp, NSStatusWindowLevel
            nsapp = NSApp()
            if nsapp:
                w = nsapp.keyWindow() or nsapp.mainWindow()
                if w:
                    w.setLevel_(NSStatusWindowLevel if on else 0)
                    w.orderFrontRegardless()
        except Exception:
            # PyObjC 未導入なら無視（Qt raise_ で足りる事が多い）
            pass
    # Linux は Qt の raise_ と WindowStaysOnTopHint で足りる事が多い


def activate_for_input(widget):
    """
    操作解禁時に“確実に”入力フォーカスを与える。
    Qt ベースで段階押し上げ。Windows では SetForegroundWindow も試す。
    """
    def _activate():
        widget.raise_()
        widget.activateWindow()
        widget.setFocus(Qt.ActiveWindowFocusReason)
    for delay in (0, 80, 160):
        QTimer.singleShot(delay, _activate)

    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(int(widget.winId()))
        except Exception:
            pass


def show_fullscreen_borderless(widget, screen=None):
    """
    “独占フルスクリーン”は使わず、ボーダレス全画面（または最大化）に統一。
    → タイマー等の最前面ウィンドウを上に出しやすくする。
    """
    widget.setAttribute(Qt.WA_NativeWindow, True)
    widget.winId()

    if screen is None:
        wh = widget.windowHandle()
        screen = wh.screen() if wh and wh.screen() else QGuiApplication.primaryScreen()
    if screen is not None:
        try:
            wh = widget.windowHandle()
            if wh:
                wh.setScreen(screen)
        except Exception:
            pass

    f = widget.windowFlags()
    f |= Qt.FramelessWindowHint | Qt.Window
    f &= ~Qt.WindowStaysOnTopHint  # ← ゲーム側はTopMostにしない（タイマーを上に出すため）
    widget.setWindowFlags(f)
    widget.showFullScreen()

