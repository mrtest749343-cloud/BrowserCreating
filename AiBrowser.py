"""
browser.py — A modern single-file PyQt5 desktop browser.
Run:  pip install PyQt5 PyQtWebEngine  then  python browser.py
"""

import re, sys, logging
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QToolBar, QLineEdit, QAction, QStatusBar, QProgressBar,
    QSizePolicy, QPushButton, QShortcut,
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QCoreApplication
from PyQt5.QtGui import QKeySequence

# ── Constants ────────────────────────────────────────────────────────────────
HOME     = "https://www.google.com"
APP_NAME = "PyBrowser"
log      = logging.getLogger(APP_NAME)
logging.basicConfig(format="[%(asctime)s] %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S", level=logging.DEBUG)

STYLE = """
QMainWindow, QWidget          { background:#1a1b22; color:#dde1f0;
                                font:13px 'Segoe UI','SF Pro Text',sans-serif; }
QToolBar                      { background:#13141a; border-bottom:1px solid #2a2b36;
                                padding:4px 6px; spacing:4px; }
QToolBar QToolButton          { background:transparent; border:none; border-radius:5px;
                                padding:4px 8px; color:#9095a8; font-size:16px; }
QToolBar QToolButton:hover    { background:#22232e; color:#fff; }
QToolBar QToolButton:disabled { color:#383944; }
QLineEdit                     { background:#22232e; border:1px solid #33343f;
                                border-radius:7px; padding:5px 12px; color:#dde1f0; }
QLineEdit:focus               { border:1px solid #5b6cf8; }
QTabWidget::pane              { border:none; }
QTabBar                       { background:#13141a; }
QTabBar::tab                  { background:#13141a; color:#6b6f80; border:none;
                                border-right:1px solid #22232e;
                                padding:8px 16px; min-width:90px; max-width:200px; }
QTabBar::tab:selected         { background:#1a1b22; color:#dde1f0;
                                border-bottom:2px solid #5b6cf8; }
QTabBar::tab:hover:!selected  { background:#1e1f28; color:#b0b4c8; }
QStatusBar                    { background:#13141a; border-top:1px solid #22232e;
                                color:#555870; font-size:11px; }
QProgressBar                  { background:#22232e; border:none; border-radius:3px;
                                max-height:3px; }
QProgressBar::chunk           { background:#5b6cf8; border-radius:3px; }
QPushButton                   { background:transparent; border:none; border-radius:5px;
                                color:#9095a8; padding:4px 10px; font-size:16px; }
QPushButton:hover             { background:#22232e; color:#fff; }
"""

# ── URL helpers ──────────────────────────────────────────────────────────────
_DOMAIN_RE = re.compile(
    r"^(localhost|(\d{1,3}\.){3}\d{1,3}|([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})"
    r"(:\d+)?(/.*)?$"
)

def to_url(raw: str) -> QUrl:
    raw = raw.strip()
    if not raw:
        return QUrl(HOME)
    for scheme in ("http://", "https://", "ftp://", "file://", "about:", "data:"):
        if raw.lower().startswith(scheme):
            return QUrl(raw)
    if _DOMAIN_RE.match(raw):
        return QUrl("https://" + raw)
    query = QUrl.toPercentEncoding(raw).data().decode()
    return QUrl(f"https://www.google.com/search?q={query}")

# ── BrowserView ──────────────────────────────────────────────────────────────
class BrowserView(QWidget):
    """One tab's web viewport. Emits clean signals; hides WebEngine internals."""
    url_changed   = pyqtSignal(QUrl)
    title_changed = pyqtSignal(str)
    load_started  = pyqtSignal()
    load_finished = pyqtSignal(bool)
    load_progress = pyqtSignal(int)
    link_hovered  = pyqtSignal(str)

    def __init__(self, url=HOME, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._wv = QWebEngineView(self)
        layout.addWidget(self._wv)

        self._wv.urlChanged.connect(self.url_changed)
        self._wv.titleChanged.connect(self.title_changed)
        self._wv.loadStarted.connect(self.load_started)
        self._wv.loadFinished.connect(self.load_finished)
        self._wv.loadProgress.connect(self.load_progress)
        self._wv.page().linkHovered.connect(self.link_hovered)
        self._wv.loadFinished.connect(lambda ok: ok or log.warning("Failed: %s", self.url()))

        self.navigate(url)

    def navigate(self, target):
        url = to_url(target) if isinstance(target, str) else target
        log.debug("→ %s", url.toString())
        self._wv.load(url)

    def url(self):        return self._wv.url()
    def title(self):      return self._wv.title() or "New Tab"
    def back(self):       self._wv.back()
    def forward(self):    self._wv.forward()
    def reload(self):     self._wv.reload()
    def stop(self):       self._wv.stop()
    def home(self):       self.navigate(HOME)
    def can_back(self):   return self._wv.history().canGoBack()
    def can_fwd(self):    return self._wv.history().canGoForward()

# ── NavBar ───────────────────────────────────────────────────────────────────
class NavBar(QToolBar):
    """Toolbar that drives whichever BrowserView is currently active."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(False)
        self._view   = None
        self._slots  = []

        self._back    = self._act("◀", "Back (Alt+Left)",    lambda: self._view and self._view.back())
        self._fwd     = self._act("▶", "Forward (Alt+Right)",lambda: self._view and self._view.fwd() or self._view.forward())
        self._reload  = self._act("↺", "Reload (F5)",        self._do_reload)
        self._home_a  = self._act("⌂", "Home",               lambda: self._view and self._view.home())
        self.addSeparator()

        self._url = QLineEdit(); self._url.setPlaceholderText("Search or enter address…")
        self._url.setClearButtonEnabled(True)
        self._url.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._url.returnPressed.connect(self._navigate)
        self.addWidget(self._url)
        self.addSeparator()

        self._progress = QProgressBar(); self._progress.setFixedWidth(72)
        self._progress.setTextVisible(False); self._progress.hide()
        self.addWidget(self._progress)

    def _act(self, text, tip, fn):
        a = QAction(text, self); a.setToolTip(tip)
        a.triggered.connect(fn); self.addAction(a); return a

    def attach(self, view: BrowserView):
        for sig, slot in self._slots:
            try: sig.disconnect(slot)
            except: pass
        self._view  = view
        self._slots = [
            (view.url_changed,   self._on_url),
            (view.load_started,  self._on_start),
            (view.load_finished, self._on_done),
            (view.load_progress, self._progress.setValue),
        ]
        for sig, slot in self._slots:
            sig.connect(slot)
        self._url.setText(view.url().toString())
        self._sync_buttons()

    def _navigate(self):
        if self._view:
            self._view.navigate(self._url.text())
            self._url.clearFocus()

    def _do_reload(self):
        if self._view: self._view.reload()

    def _on_url(self, url):
        if not self._url.hasFocus():
            self._url.setText(url.toString())
        self._sync_buttons()

    def _on_start(self):
        self._reload.setText("✕"); self._reload.setToolTip("Stop")
        self._reload.triggered.disconnect(); self._reload.triggered.connect(lambda: self._view and self._view.stop())
        self._progress.show(); self._progress.setValue(0)

    def _on_done(self, _):
        self._reload.setText("↺"); self._reload.setToolTip("Reload (F5)")
        self._reload.triggered.disconnect(); self._reload.triggered.connect(self._do_reload)
        self._progress.hide(); self._sync_buttons()

    def _sync_buttons(self):
        self._back.setEnabled(bool(self._view and self._view.can_back()))
        self._fwd .setEnabled(bool(self._view and self._view.can_fwd()))

    def focus_url(self):
        self._url.setFocus(); self._url.selectAll()

# ── Tabs ─────────────────────────────────────────────────────────────────────
class TabBar(QTabWidget):
    switched = pyqtSignal(object)  # BrowserView

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDocumentMode(True); self.setTabsClosable(True); self.setMovable(True)

        btn = QPushButton("＋"); btn.setToolTip("New tab (Ctrl+T)")
        btn.clicked.connect(self.new_tab)
        self.setCornerWidget(btn, Qt.TopRightCorner)

        self.currentChanged.connect(self._switched)
        self.tabCloseRequested.connect(self._close)
        self.new_tab()

    def new_tab(self, url=HOME) -> BrowserView:
        v = BrowserView(url, self)
        v.title_changed.connect(lambda t, v=v: self._retitle(v, t))
        v.icon_changed  = lambda i, v=v: None   # placeholder hook for future icon support
        idx = self.addTab(v, "New Tab")
        self.setCurrentIndex(idx)
        return v

    def _switched(self, idx):
        v = self.widget(idx)
        if isinstance(v, BrowserView):
            self.switched.emit(v)

    def _close(self, idx):
        if self.count() <= 1:
            self.widget(0).home(); return
        w = self.widget(idx); self.removeTab(idx)
        if w: w.deleteLater()

    def _retitle(self, view, title):
        i = self.indexOf(view)
        if i >= 0:
            self.setTabText(i, (title[:24] + "…") if len(title) > 25 else title or "New Tab")

    def current(self) -> BrowserView | None:
        w = self.currentWidget(); return w if isinstance(w, BrowserView) else None

    def close_current(self): self._close(self.currentIndex())
    def next(self):  self.setCurrentIndex((self.currentIndex()+1) % self.count())
    def prev(self):  self.setCurrentIndex((self.currentIndex()-1) % self.count())

# ── Main Window ──────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(900, 600); self.resize(1280, 800)

        self._nav  = NavBar(self);         self.addToolBar(self._nav)
        self._tabs = TabBar(self);         self.setCentralWidget(self._tabs)
        self._sb   = QStatusBar(self);     self.setStatusBar(self._sb)

        self._tabs.switched.connect(self._activate)
        self._activate(self._tabs.current())

        # Shortcuts
        def sc(key, fn): QShortcut(QKeySequence(key), self).activated.connect(fn)
        sc("Ctrl+T",          self._tabs.new_tab)
        sc("Ctrl+W",          self._tabs.close_current)
        sc("F5",              lambda: self._tabs.current() and self._tabs.current().reload())
        sc("Ctrl+R",          lambda: self._tabs.current() and self._tabs.current().reload())
        sc("Escape",          lambda: self._tabs.current() and self._tabs.current().stop())
        sc("Alt+Left",        lambda: self._tabs.current() and self._tabs.current().back())
        sc("Alt+Right",       lambda: self._tabs.current() and self._tabs.current().forward())
        sc("Ctrl+L",          self._nav.focus_url)
        sc("Ctrl+Tab",        self._tabs.next)
        sc("Ctrl+Shift+Tab",  self._tabs.prev)

    def _activate(self, view):
        if not view: return
        self._nav.attach(view)
        view.link_hovered.connect(lambda u: self._sb.showMessage(u) if u else self._sb.clearMessage())
        view.title_changed.connect(lambda t: self.setWindowTitle(f"{t} — {APP_NAME}" if t else APP_NAME))
        self.setWindowTitle(f"{view.title()} — {APP_NAME}")

# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps,    True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLE)
    win = MainWindow(); win.show()
    sys.exit(app.exec_())