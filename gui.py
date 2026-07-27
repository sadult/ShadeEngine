"""
Shade Engine - SNI Spoof GUI (modern redesign).

Single-executable design: the GUI and the engine live in ONE exe.
When you press START, the GUI relaunches *itself* with the hidden `--engine`
flag, so there is no separate engine.exe to ship or lose.
"""

import json
import os
import sys
import time

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QPushButton, QTextBrowser,
                             QLabel, QFrame, QStackedWidget, QScrollArea,
                             QLineEdit, QComboBox, QMessageBox)
from PyQt6.QtGui import (QColor, QTextCursor, QDesktopServices, QFont, QPixmap,
                         QIcon, QIntValidator, QPalette)
from PyQt6.QtCore import Qt, QUrl, QProcess, QPoint

# ==========================================================
#  Branding / metadata
# ==========================================================
APP_NAME = "Shade Engine"
APP_TAGLINE = "SNI Spoof"
APP_VERSION = "1.0.0"
AUTHOR = "@Bitologist"
GITHUB_URL = "https://github.com/sadult/ShadeEngine"
GITHUB_ISSUES_URL = "https://github.com/sadult/ShadeEngine/issues"
CLOUD_CONFIG_URL = "https://github.com/sadult/ShadeEngine/blob/main/config.md"
CLOUD_CONFIG_RAW_URL = "https://raw.githubusercontent.com/sadult/ShadeEngine/main/config.md"
TELEGRAM_URL = "https://t.me/Bitologist"

# Common fake-SNI presets offered in the config editor.
SNI_PRESETS = ["mci.ir", "mtn.ir", "rightel.ir", "digikala.com",
              "aparat.com", "varzesh3.com", "snapp.ir", "www.google.com"]


def resource_path(relative_path):
    """Absolute path to a bundled resource (works in dev and PyInstaller)."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)


def app_dir():
    """Directory next to the running exe (where config.json lives)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def config_path():
    return os.path.join(app_dir(), "config.json")


def local_profiles_path():
    return os.path.join(app_dir(), "profiles.txt")


def load_app_icon():
    for name in ("assets/icon.ico", "assets/icon.png", "icon.ico", "icon.png"):
        p = resource_path(name)
        if os.path.exists(p):
            return QIcon(p)
    return QIcon()


# ----------------------------------------------------------
#  Sidebar navigation button (emoji badge + label)
# ----------------------------------------------------------
class NavButton(QPushButton):
    def __init__(self, emoji, text):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(46)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(12)

        self.badge = QLabel(emoji)
        self.badge.setObjectName("nav_badge")
        self.badge.setFixedSize(30, 30)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.lbl = QLabel(text)
        self.lbl.setObjectName("nav_text")
        self.lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        lay.addWidget(self.badge)
        lay.addWidget(self.lbl)
        lay.addStretch()
        self.set_selected(False)

    def set_selected(self, sel):
        if sel:
            self.setStyleSheet("""
                QPushButton { text-align:left; border:1px solid #5A48A8; border-radius:11px;
                    background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 rgba(157,78,221,0.42), stop:1 rgba(123,44,191,0.16)); }
                #nav_badge { border-radius:9px; color:#ffffff; font-size:15px;
                    background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #9D4EDD, stop:1 #6A1F9A); }
                #nav_text { color:#FFFFFF; font-size:13px; font-weight:700; background:transparent; }
                QLabel { background:transparent; }
            """)
        else:
            self.setStyleSheet("""
                QPushButton { text-align:left; border:1px solid transparent; border-radius:11px; background:transparent; }
                QPushButton:hover { background:rgba(157,78,221,0.20); }
                #nav_badge { border-radius:9px; color:#E2DBF8; font-size:15px; background:#2C2358; }
                #nav_text { color:#D0C7F0; font-size:13px; font-weight:600; background:transparent; }
                QLabel { background:transparent; }
            """)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(1080, 700)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(load_app_icon())

        self.is_debug_mode = False
        self.dragPos = QPoint()
        self.nav_buttons = []
        self.editing_config = False

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.process_finished)
        # Hide the child engine console window on Windows (keeps stdout piped).
        try:
            def _mod(args):
                args.flags |= 0x08000000  # CREATE_NO_WINDOW
            self.process.setCreateProcessArgumentsModifier(_mod)
        except Exception:
            pass

        self.ensure_config()
        self.setup_ui()
        self.log_html_print("System", "Proxy Engine initialized successfully.", color="#CAC0EC")

    def resource_path(self, relative_path):
        return resource_path(relative_path)

    # ======================================================
    #  UI
    # ======================================================
    def setup_ui(self):
        self.setStyleSheet("""
            /* ---- Global reset: kill every default grey widget background ---- */
            QMainWindow, QMainWindow > QWidget { background:transparent; }
            QWidget { background:transparent; color:#F4F1FE; }
            QFrame { background:transparent; border:none; }
            QLabel { background:transparent; color:#F4F1FE; }
            QStackedWidget, QStackedWidget > QWidget { background:transparent; }
            QScrollArea { background:transparent; border:none; }
            QScrollArea > QWidget { background:transparent; }
            QScrollArea > QWidget > QWidget { background:transparent; }
            QAbstractScrollArea { background:transparent; }
            QAbstractScrollArea::viewport, QScrollArea::viewport,
            QTextBrowser::viewport { background:transparent; }
            QToolTip {
                background:#282050; color:#F7F4FF; border:1px solid #473A96;
                border-radius:6px; padding:5px 8px;
            }

            QWidget#main_container {
                background:#171130; border:1px solid #453892; border-radius:18px;
            }
            QFrame#sidebar_card { background:#1E1740; border:1px solid #3E3280; border-radius:14px; }
            QFrame#hero_card {
                background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #251C4E, stop:1 #1F1743);
                border:1px solid #453892; border-radius:14px;
            }
            QFrame#panel_card, QFrame#term_card {
                background:#1B1439; border:1px solid #3E3280; border-radius:14px;
            }
            QLabel { color:#F4F1FE; }

            /* Terminal */
            QTextBrowser {
                background:transparent; color:#EAE4FC;
                font-family:'JetBrains Mono','Cascadia Code','Consolas',monospace;
                font-size:13px; border:none; padding:6px 14px;
            }
            QScrollBar:vertical { border:none; background:rgba(255,255,255,0.04); width:9px; margin:4px; border-radius:4px; }
            QScrollBar::handle:vertical { background:#6F5CC4; border-radius:4px; min-height:30px; }
            QScrollBar::handle:vertical:hover { background:#9D4EDD; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; }
            QScrollBar:horizontal { height:0px; }

            /* Inputs */
            QLineEdit, QComboBox {
                background:#241C48; color:#F7F4FF; border:1px solid #473A96;
                border-radius:9px; padding:9px 12px; font-size:13px;
                selection-background-color:#7B2CBF;
            }
            QLineEdit:focus, QComboBox:focus { border:1px solid #7B2CBF; }
            QComboBox::drop-down { border:none; width:22px; }
            QComboBox QAbstractItemView {
                background:#282050; color:#F7F4FF; border:1px solid #473A96;
                selection-background-color:#7B2CBF; outline:none;
            }

            /* Primary action buttons */
            QPushButton#btn_start {
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #7B2CBF, stop:1 #9D4EDD);
                color:#fff; font-size:14px; font-weight:800; letter-spacing:1.5px;
                border:none; border-radius:24px; padding:14px 30px;
            }
            QPushButton#btn_start:hover {
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #9D4EDD, stop:1 #C77DFF);
            }
            QPushButton#btn_stop {
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #F72585, stop:1 #B5179E);
                color:#fff; font-size:14px; font-weight:800; letter-spacing:1.5px;
                border:none; border-radius:24px; padding:14px 30px;
            }
            QPushButton#btn_stop:hover {
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #FF4D9D, stop:1 #F72585);
            }

            /* Pill / ghost buttons */
            QPushButton.pill {
                background:#2C2358; color:#D9A8FF; border:1px solid #473A96;
                border-radius:10px; padding:10px 16px; font-size:13px; font-weight:700;
            }
            QPushButton.pill:hover { background:#3D3178; color:#EADFFB; border:1px solid #6A55C6; }

            /* Save / confirm button */
            QPushButton.save {
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00B894, stop:1 #00F5D4);
                color:#06231C; border:none; border-radius:10px;
                padding:10px 20px; font-size:13px; font-weight:800;
            }
            QPushButton.save:hover {
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00F5D4, stop:1 #6FFCE6);
            }

            /* Contact / link cards */
            QPushButton.linkcard {
                background:#241C48; color:#F4F1FE; border:1px solid #453892;
                border-radius:12px; padding:16px 18px; font-size:14px; font-weight:700; text-align:left;
            }
            QPushButton.linkcard:hover { background:#2F2660; border:1px solid #6A55C6; }

            QLabel#pulse_on {
                border-radius:32px; font-size:26px; color:#04120F;
                background:qradialgradient(cx:0.4, cy:0.35, radius:0.9, fx:0.4, fy:0.35,
                    stop:0 #00F5D4, stop:1 #0A7B6B);
            }
            QLabel#pulse_off {
                border-radius:32px; font-size:26px; color:#2A0A18;
                background:qradialgradient(cx:0.4, cy:0.35, radius:0.9, fx:0.4, fy:0.35,
                    stop:0 #F72585, stop:1 #7A0A3E);
            }

            /* Dialogs must match the dark theme instead of the OS grey */
            QMessageBox { background:#211A45; }
            QMessageBox QLabel { color:#F7F4FF; background:transparent; font-size:13px; }
            QMessageBox QPushButton {
                background:#2C2358; color:#D9A8FF; border:1px solid #473A96;
                border-radius:9px; padding:7px 18px; font-size:12.5px; font-weight:700;
                min-width:74px;
            }
            QMessageBox QPushButton:hover {
                background:#3D3178; color:#EADFFB; border:1px solid #6A55C6;
            }
        """)

        main_container = QWidget()
        main_container.setObjectName("main_container")
        self.setCentralWidget(main_container)
        root = QVBoxLayout(main_container)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        root.addWidget(self.build_topbar())

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self.build_sidebar())
        body.addWidget(self.build_content(), 1)
        root.addLayout(body)

        self.select_nav(0)

    # ---------- Top bar ----------
    def build_topbar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(44)
        bar.setStyleSheet("#topbar { background:transparent; border:none; }")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(12)

        logo = QLabel()
        logo.setFixedSize(28, 28)
        icon_path = resource_path("assets/icon.png")
        if os.path.exists(icon_path):
            logo.setPixmap(QPixmap(icon_path).scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        else:
            logo.setText("S")
            logo.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #9D4EDD,stop:1 #5A189A);"
                               "border-radius:8px; color:#fff; font-weight:900; font-size:15px;")
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(APP_NAME.upper())
        title.setStyleSheet("color:#F7F4FF; font-size:14px; font-weight:900; letter-spacing:2px;")
        subtitle = QLabel(APP_TAGLINE)
        subtitle.setStyleSheet("color:#BFB3E6; font-size:12px; font-weight:600; letter-spacing:1px;")
        ver = QLabel(f"v{APP_VERSION}")
        ver.setStyleSheet("color:#A99CD8; font-size:11px; font-weight:700; padding:2px 8px;"
                          "border:1px solid #453892; border-radius:8px;")

        lay.addWidget(logo)
        lay.addWidget(title)
        lay.addWidget(subtitle)
        lay.addWidget(ver)
        lay.addStretch()

        btn_min = self.create_window_btn("#F9C74F", "#FFD97A", self.showMinimized)
        btn_close = self.create_window_btn("#F72585", "#FF4D9D", self.close)
        lay.addWidget(btn_min)
        lay.addWidget(btn_close)
        return bar

    def create_window_btn(self, color, hover, func):
        btn = QPushButton()
        btn.setFixedSize(13, 13)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setStyleSheet(f"QPushButton{{background:{color}; border-radius:6px;}}"
                          f"QPushButton:hover{{background:{hover};}}")
        btn.clicked.connect(func)
        return btn

    # ---------- Sidebar ----------
    def build_sidebar(self):
        card = QFrame()
        card.setObjectName("sidebar_card")
        card.setFixedWidth(240)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 16, 12, 16)
        lay.setSpacing(4)

        lay.addWidget(self.section_label("MAIN"))
        self.add_nav(lay, "\U0001F4CA", "Dashboard", lambda: self.select_nav(0))
        self.add_nav(lay, "\u2699\ufe0f", "Configuration", lambda: self.select_nav(1))
        self.add_nav(lay, "\u2601\ufe0f", "Cloud Config", self.open_onlinelist)
        self.add_nav(lay, "\U0001F4C2", "Local Profiles", self.open_locallist)

        lay.addWidget(self.section_label("SUPPORT"))
        self.add_nav(lay, "\u2753", "FAQ & Help", lambda: self.select_nav(2))
        self.add_nav(lay, "\u2709\ufe0f", "Contact", lambda: self.select_nav(3))
        self.add_nav(lay, "\U0001F41E", "Debug Mode", self.toggle_debug)
        self.add_nav(lay, "\U0001F9F9", "Clear Logs", self.clear_logs)

        lay.addStretch()
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background:#3C3070;")
        lay.addWidget(divider)
        ver = QLabel(f"v{APP_VERSION}  \u2022  {AUTHOR}")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet("color:#A99CD8; font-size:11px; font-weight:700; padding-top:8px;")
        lay.addWidget(ver)
        return card

    def section_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#A99CD8; font-size:10px; font-weight:800; letter-spacing:2px; padding:12px 10px 4px;")
        return lbl

    def add_nav(self, layout, emoji, text, func):
        btn = NavButton(emoji, text)
        btn.clicked.connect(func)
        layout.addWidget(btn)
        self.nav_buttons.append(btn)
        return btn

    def select_nav(self, index):
        page_names = ["Dashboard", "Configuration", "FAQ & Help", "Contact"]
        target = page_names[index]
        for b in self.nav_buttons:
            b.set_selected(b.lbl.text() == target)
            b.setChecked(b.lbl.text() == target)
        self.stack.setCurrentIndex(index)
        if index == 1:
            self.exit_edit_mode()
            self.refresh_config_view()

    # ---------- Content ----------
    def build_content(self):
        self.stack = QStackedWidget()
        self.stack.addWidget(self.build_dashboard())     # 0
        self.stack.addWidget(self.build_config_page())   # 1
        self.stack.addWidget(self.build_faq_page())      # 2
        self.stack.addWidget(self.build_contact_page())  # 3
        return self.stack

    def build_dashboard(self):
        page = QWidget()
        page.setAutoFillBackground(False)
        page.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("hero_card")
        hero.setFixedHeight(104)
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(22, 16, 22, 16)
        hl.setSpacing(18)

        self.pulse = QLabel("\u26A1")
        self.pulse.setObjectName("pulse_off")
        self.pulse.setFixedSize(64, 64)
        self.pulse.setAlignment(Qt.AlignmentFlag.AlignCenter)

        info = QVBoxLayout()
        info.setSpacing(3)
        self.status_title = QLabel("ENGINE OFFLINE")
        self.status_title.setStyleSheet("color:#F72585; font-size:20px; font-weight:900; letter-spacing:1px;")
        self.status_sub = QLabel("Press Start to activate the tunnel.")
        self.status_sub.setStyleSheet("color:#CAC0EC; font-size:12.5px;")
        info.addWidget(self.status_title)
        info.addWidget(self.status_sub)

        self.btn_toggle = QPushButton("START ENGINE")
        self.btn_toggle.setObjectName("btn_start")
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_toggle.setMinimumWidth(180)
        self.btn_toggle.clicked.connect(self.toggle_engine)

        hl.addWidget(self.pulse)
        hl.addLayout(info)
        hl.addStretch()
        hl.addWidget(self.btn_toggle)
        lay.addWidget(hero)

        term_card = QFrame()
        term_card.setObjectName("term_card")
        tl = QVBoxLayout(term_card)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)

        head = QFrame()
        head.setFixedHeight(42)
        head.setStyleSheet("background:transparent; border:none; border-bottom:1px solid #382C6B;")
        head_l = QHBoxLayout(head)
        head_l.setContentsMargins(16, 0, 16, 0)
        head_l.setSpacing(7)
        for c in ("#F72585", "#F9C74F", "#00F5D4"):
            d = QLabel()
            d.setFixedSize(10, 10)
            d.setStyleSheet(f"background:{c}; border-radius:5px;")
            head_l.addWidget(d)
        tlabel = QLabel("LIVE CONSOLE")
        tlabel.setStyleSheet("color:#B3A6E0; font-size:11px; font-weight:700; letter-spacing:2px; padding-left:8px;")
        head_l.addWidget(tlabel)
        head_l.addStretch()
        self.term_badge = QLabel("\u25CF OFFLINE")
        self.term_badge.setStyleSheet("background:rgba(247,37,133,0.24); color:#F72585; font-size:10px;"
                                      "font-weight:800; padding:5px 11px; border-radius:11px; letter-spacing:1px;")
        head_l.addWidget(self.term_badge)
        tl.addWidget(head)

        self.terminal = QTextBrowser()
        self.terminal.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.terminal.setOpenExternalLinks(True)
        self.terminal.setFrameShape(QFrame.Shape.NoFrame)
        self.terminal.setAutoFillBackground(False)
        self.terminal.viewport().setAutoFillBackground(False)
        self.terminal.viewport().setStyleSheet("background:transparent;")
        tl.addWidget(self.terminal)
        lay.addWidget(term_card, 1)
        return page

    # ---------- Configuration page (in-app editor) ----------
    def build_config_page(self):
        page = self.scroll_page()
        body = page.body
        body.addWidget(self.page_title("\u2699\ufe0f  Configuration",
                                       "Review your current settings, edit them locally, or open the cloud config guide."))

        # ----- VIEW card -----
        self.cfg_view_card = QFrame()
        self.cfg_view_card.setObjectName("panel_card")
        vcl = QVBoxLayout(self.cfg_view_card)
        vcl.setContentsMargins(22, 20, 22, 22)
        vcl.setSpacing(14)

        head = QLabel("CURRENT CONFIGURATION")
        head.setStyleSheet("color:#B3A6E0; font-size:11px; font-weight:800; letter-spacing:2px;")
        vcl.addWidget(head)

        self.config_view = QLabel("Loading config...")
        self.config_view.setStyleSheet("color:#E2DBF8; font-family:'Consolas',monospace; font-size:14px;"
                                       "background:#241C48; border:1px solid #3E3280; border-radius:10px; padding:18px;")
        self.config_view.setWordWrap(True)
        self.config_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        vcl.addWidget(self.config_view)

        row = QHBoxLayout()
        row.setSpacing(10)
        btn_edit = QPushButton("\u270F\ufe0f  Edit")
        btn_edit.setProperty("class", "pill")
        btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_edit.clicked.connect(self.enter_edit_mode)
        btn_reload = QPushButton("\U0001F504  Reload")
        btn_reload.setProperty("class", "pill")
        btn_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reload.clicked.connect(self.refresh_config_view)
        btn_copy = QPushButton("\U0001F4CB  Copy")
        btn_copy.setProperty("class", "pill")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.clicked.connect(self.copy_config)
        btn_cloud = QPushButton("☁️  Cloud config")
        btn_cloud.setProperty("class", "pill")
        btn_cloud.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cloud.clicked.connect(self.open_onlinelist)
        row.addWidget(btn_edit)
        row.addWidget(btn_reload)
        row.addWidget(btn_copy)
        row.addWidget(btn_cloud)
        row.addStretch()
        vcl.addLayout(row)
        body.addWidget(self.cfg_view_card)

        # ----- EDIT card (hidden until Edit is pressed) -----
        self.cfg_edit_card = QFrame()
        self.cfg_edit_card.setObjectName("panel_card")
        ecl = QVBoxLayout(self.cfg_edit_card)
        ecl.setContentsMargins(22, 20, 22, 22)
        ecl.setSpacing(14)

        ehead = QLabel("EDIT CONFIGURATION")
        ehead.setStyleSheet("color:#C77DFF; font-size:11px; font-weight:800; letter-spacing:2px;")
        ecl.addWidget(ehead)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)

        self.in_listen_host = QLineEdit()
        self.in_listen_port = QLineEdit()
        self.in_listen_port.setValidator(QIntValidator(1, 65535, self))
        self.in_connect_ip = QLineEdit()
        self.in_connect_port = QLineEdit()
        self.in_connect_port.setValidator(QIntValidator(1, 65535, self))

        self.in_fake_sni = QComboBox()
        self.in_fake_sni.setEditable(True)
        self.in_fake_sni.addItems(SNI_PRESETS)

        grid.addWidget(self.field_label("Listen Host", "Local address the proxy binds to"), 0, 0)
        grid.addWidget(self.in_listen_host, 0, 1)
        grid.addWidget(self.field_label("Listen Port", "Local port for your client (1-65535)"), 1, 0)
        grid.addWidget(self.in_listen_port, 1, 1)
        grid.addWidget(self.field_label("Fake SNI", "Domain shown in the spoofed TLS handshake"), 2, 0)
        grid.addWidget(self.in_fake_sni, 2, 1)
        grid.addWidget(self.field_label("Connect IP", "Real destination server IP"), 3, 0)
        grid.addWidget(self.in_connect_ip, 3, 1)
        grid.addWidget(self.field_label("Connect Port", "Destination port (usually 443)"), 4, 0)
        grid.addWidget(self.in_connect_port, 4, 1)
        grid.setColumnStretch(1, 1)
        ecl.addLayout(grid)

        erow = QHBoxLayout()
        erow.setSpacing(10)
        btn_save = QPushButton("\U0001F4BE  Save")
        btn_save.setProperty("class", "save")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self.save_config)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setProperty("class", "pill")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.exit_edit_mode)
        btn_reset = QPushButton("\u21BA  Reset to defaults")
        btn_reset.setProperty("class", "pill")
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.clicked.connect(self.reset_defaults)
        erow.addWidget(btn_save)
        erow.addWidget(btn_cancel)
        erow.addWidget(btn_reset)
        erow.addStretch()
        ecl.addLayout(erow)

        self.cfg_edit_card.setVisible(False)
        body.addWidget(self.cfg_edit_card)

        note = QLabel("Tip: changing the config while the engine is running requires a restart of the engine.")
        note.setStyleSheet("color:#A99CD8; font-size:12px;")
        note.setWordWrap(True)
        body.addWidget(note)
        body.addStretch()
        return page.container

    def field_label(self, title, subtitle):
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        t = QLabel(title)
        t.setStyleSheet("color:#F7F4FF; font-size:13.5px; font-weight:700;")
        s = QLabel(subtitle)
        s.setStyleSheet("color:#B0A3DD; font-size:11px;")
        s.setWordWrap(True)
        v.addWidget(t)
        v.addWidget(s)
        w.setFixedWidth(230)
        return w

    def build_faq_page(self):
        page = self.scroll_page()
        body = page.body
        body.addWidget(self.page_title("\u2753  FAQ & Help",
                                       "Quick answers and links to the full documentation."))

        faqs = [
            ("What is Shade Engine?",
             "A packet-manipulation tool that spoofs the TLS SNI to improve connectivity with "
             "specific configurations under restricted networks."),
            ("Why must I run it as Administrator?",
             "The WinDivert driver needs elevated privileges to inject packets. The app already "
             "requests admin automatically; just approve the prompt."),
            ("How do I configure it?",
             "Open Configuration, press Edit, set the correct Connect IP and ports, press Save, then Start. Use Cloud Config to read the latest config.md from the GitHub repository."),
            ("The console shows nothing - is it working?",
             "When the status turns green (INJECTING) the engine is active. Enable Debug Mode to see detailed backend logs."),
            ("Do I need a separate engine.exe?",
             "No. The engine is built into this single executable - there is nothing else to ship or place beside it."),
        ]
        for q, a in faqs:
            body.addWidget(self.faq_item(q, a))

        card = QFrame()
        card.setObjectName("panel_card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 18)
        cl.setSpacing(12)
        head = QLabel("Need more? Check the full docs on GitHub.")
        head.setStyleSheet("color:#E2DBF8; font-size:13.5px; font-weight:600;")
        cl.addWidget(head)
        row = QHBoxLayout()
        row.setSpacing(10)
        gh = QPushButton("\U0001F4D6  Open GitHub Repository")
        gh.setProperty("class", "pill")
        gh.setCursor(Qt.CursorShape.PointingHandCursor)
        gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        iss = QPushButton("\U0001F41E  Report an Issue")
        iss.setProperty("class", "pill")
        iss.setCursor(Qt.CursorShape.PointingHandCursor)
        iss.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_ISSUES_URL)))
        row.addWidget(gh)
        row.addWidget(iss)
        row.addStretch()
        cl.addLayout(row)
        body.addWidget(card)
        body.addStretch()
        return page.container

    def faq_item(self, question, answer):
        card = QFrame()
        card.setObjectName("panel_card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 14)
        cl.setSpacing(6)
        q = QLabel("\u25B8  " + question)
        q.setStyleSheet("color:#C77DFF; font-size:14px; font-weight:800;")
        a = QLabel(answer)
        a.setWordWrap(True)
        a.setStyleSheet("color:#CAC0EC; font-size:13px; line-height:1.5;")
        cl.addWidget(q)
        cl.addWidget(a)
        return card

    def build_contact_page(self):
        page = self.scroll_page()
        body = page.body
        body.addWidget(self.page_title("\u2709\ufe0f  Contact the Developer",
                                       "Questions, feedback or collaboration? Reach out below."))

        body.addWidget(self.contact_card("\U0001F4AC", "Telegram", TELEGRAM_URL, TELEGRAM_URL))
        body.addWidget(self.contact_card("\U0001F419", "GitHub Repository", "github.com/sadult/ShadeEngine", GITHUB_URL))
        body.addWidget(self.contact_card("\U0001F41E", "Report a Bug", "Open an issue on GitHub", GITHUB_ISSUES_URL))

        credit = QLabel(f"Crafted with \u2764\ufe0f by {AUTHOR}  \u2022  {APP_NAME} v{APP_VERSION}")
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credit.setStyleSheet("color:#A99CD8; font-size:12px; font-weight:600; padding-top:10px;")
        body.addWidget(credit)
        body.addStretch()
        return page.container

    def contact_card(self, emoji, title, subtitle, url):
        btn = QPushButton()
        btn.setProperty("class", "linkcard")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setMinimumHeight(66)
        lay = QHBoxLayout(btn)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(14)

        badge = QLabel(emoji)
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        badge.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #3D3178,stop:1 #2F2660);"
                            "border-radius:11px; font-size:19px;")
        txt = QVBoxLayout()
        txt.setSpacing(2)
        t = QLabel(title)
        t.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        t.setStyleSheet("color:#F7F4FF; font-size:14.5px; font-weight:800; background:transparent;")
        s = QLabel(subtitle)
        s.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        s.setStyleSheet("color:#BFB3E6; font-size:12px; background:transparent;")
        txt.addWidget(t)
        txt.addWidget(s)

        arrow = QLabel("\u2197")
        arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        arrow.setStyleSheet("color:#7B2CBF; font-size:20px; font-weight:800; background:transparent;")

        lay.addWidget(badge)
        lay.addLayout(txt)
        lay.addStretch()
        lay.addWidget(arrow)
        btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        return btn

    def scroll_page(self):
        class _P:
            pass
        p = _P()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        scroll.setStyleSheet("background:transparent; border:none;")
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setStyleSheet("background:transparent;")
        inner = QWidget()
        inner.setAutoFillBackground(False)
        inner.setStyleSheet("background:transparent;")
        body = QVBoxLayout(inner)
        body.setContentsMargins(4, 2, 10, 4)
        body.setSpacing(12)
        scroll.setWidget(inner)
        p.container = scroll
        p.body = body
        return p

    def page_title(self, title, subtitle):
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 0, 6)
        v.setSpacing(3)
        t = QLabel(title)
        t.setStyleSheet("color:#F7F4FF; font-size:22px; font-weight:900;")
        s = QLabel(subtitle)
        s.setStyleSheet("color:#BFB3E6; font-size:13px;")
        v.addWidget(t)
        v.addWidget(s)
        return w

    # ======================================================
    #  Window drag
    # ======================================================
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.pos().y() < 56:
            self.dragPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if hasattr(self, "dragPos") and not self.dragPos.isNull():
            self.move(self.pos() + event.globalPosition().toPoint() - self.dragPos)
            self.dragPos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.dragPos = QPoint()

    # ======================================================
    #  Config / profiles
    # ======================================================
    def default_config(self):
        return {
            "LISTEN_HOST": "127.0.0.1",
            "LISTEN_PORT": 8080,
            "FAKE_SNI": "mci.ir",
            "CONNECT_IP": "1.1.1.1",
            "CONNECT_PORT": 443,
        }

    def ensure_config(self):
        if not os.path.exists(config_path()):
            try:
                with open(config_path(), "w", encoding="utf-8") as f:
                    json.dump(self.default_config(), f, indent=4)
            except Exception:
                pass

    def read_config(self):
        try:
            with open(config_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return dict(self.default_config())

    def refresh_config_view(self):
        if not hasattr(self, "config_view"):
            return
        try:
            self.ensure_config()
            data = self.read_config()
            lines = [f"<b style='color:#C77DFF'>{k}</b> : <span style='color:#00F5D4'>{v}</span>"
                     for k, v in data.items()]
            self.config_view.setText("<br>".join(lines))
        except Exception as e:
            self.config_view.setText(f"Cannot read config: {e}")

    def enter_edit_mode(self):
        data = self.read_config()
        self.in_listen_host.setText(str(data.get("LISTEN_HOST", "127.0.0.1")))
        self.in_listen_port.setText(str(data.get("LISTEN_PORT", 8080)))
        self.in_fake_sni.setCurrentText(str(data.get("FAKE_SNI", "mci.ir")))
        self.in_connect_ip.setText(str(data.get("CONNECT_IP", "1.1.1.1")))
        self.in_connect_port.setText(str(data.get("CONNECT_PORT", 443)))
        self.editing_config = True
        self.cfg_view_card.setVisible(False)
        self.cfg_edit_card.setVisible(True)

    def exit_edit_mode(self):
        self.editing_config = False
        if hasattr(self, "cfg_edit_card"):
            self.cfg_edit_card.setVisible(False)
        if hasattr(self, "cfg_view_card"):
            self.cfg_view_card.setVisible(True)

    def reset_defaults(self):
        d = self.default_config()
        self.in_listen_host.setText(str(d["LISTEN_HOST"]))
        self.in_listen_port.setText(str(d["LISTEN_PORT"]))
        self.in_fake_sni.setCurrentText(str(d["FAKE_SNI"]))
        self.in_connect_ip.setText(str(d["CONNECT_IP"]))
        self.in_connect_port.setText(str(d["CONNECT_PORT"]))

    def save_config(self):
        host = self.in_listen_host.text().strip()
        sni = self.in_fake_sni.currentText().strip()
        connect_ip = self.in_connect_ip.text().strip()
        errors = []
        if not host:
            errors.append("Listen Host cannot be empty.")
        if not sni:
            errors.append("Fake SNI cannot be empty.")
        if not connect_ip:
            errors.append("Connect IP cannot be empty.")
        try:
            listen_port = int(self.in_listen_port.text())
            if not (1 <= listen_port <= 65535):
                raise ValueError
        except ValueError:
            errors.append("Listen Port must be a number between 1 and 65535.")
            listen_port = None
        try:
            connect_port = int(self.in_connect_port.text())
            if not (1 <= connect_port <= 65535):
                raise ValueError
        except ValueError:
            errors.append("Connect Port must be a number between 1 and 65535.")
            connect_port = None

        if errors:
            QMessageBox.warning(self, "Invalid configuration", "\n".join(errors))
            return

        data = {
            "LISTEN_HOST": host,
            "LISTEN_PORT": listen_port,
            "FAKE_SNI": sni,
            "CONNECT_IP": connect_ip,
            "CONNECT_PORT": connect_port,
        }
        try:
            with open(config_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"Could not write config.json:\n{e}")
            return

        self.exit_edit_mode()
        self.refresh_config_view()
        self.log_html_print("System", "Configuration saved.", color="#00F5D4")
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.log_html_print("System", "Restart the engine to apply the new settings.", color="#F9C74F")

    def copy_config(self):
        try:
            with open(config_path(), "r", encoding="utf-8") as f:
                text = f.read()
            QApplication.clipboard().setText(text)
            self.log_html_print("System", "Config copied to clipboard.", color="#CAC0EC")
        except Exception as e:
            self.log_html_print("System", f"Cannot copy config: {e}", color="#F72585")

    def open_locallist(self):
        path = local_profiles_path()
        if not os.path.exists(path):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("# YOUR LOCAL CONFIGS GO HERE\n")
            except Exception:
                pass
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            self.log_html_print("System", f"Cannot open file: {e}", color="#F72585")

    def open_onlinelist(self):
        try:
            QDesktopServices.openUrl(QUrl(CLOUD_CONFIG_URL))
            self.log_html_print("System", "Opened cloud config: github.com/sadult/ShadeEngine/config.md", color="#CAC0EC")
        except Exception as e:
            self.log_html_print("System", f"Cannot open cloud config: {e}", color="#F72585")

    def clear_logs(self):
        self.terminal.clear()
        self.log_html_print("System", "Console cleared.", color="#CAC0EC")

    def toggle_debug(self):
        self.is_debug_mode = not self.is_debug_mode
        state = "ON" if self.is_debug_mode else "OFF"
        color = "#00F5D4" if self.is_debug_mode else "#CAC0EC"
        self.log_html_print("System", f"Debug mode {state}.", color=color)

    # ======================================================
    #  Engine process (single-exe self relaunch)
    # ======================================================
    def toggle_engine(self):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.start_engine()
        else:
            self.stop_engine()

    def set_status(self, online):
        if online:
            self.pulse.setObjectName("pulse_on")
            self.status_title.setText("ENGINE ONLINE")
            self.status_title.setStyleSheet("color:#00F5D4; font-size:20px; font-weight:900; letter-spacing:1px;")
            self.status_sub.setText("Packets injecting \u2022 tunnel active.")
            self.btn_toggle.setText("STOP ENGINE")
            self.btn_toggle.setObjectName("btn_stop")
            self.term_badge.setText("\u25CF INJECTING")
            self.term_badge.setStyleSheet("background:rgba(0,245,212,0.22); color:#00F5D4; font-size:10px;"
                                          "font-weight:800; padding:5px 11px; border-radius:11px; letter-spacing:1px;")
        else:
            self.pulse.setObjectName("pulse_off")
            self.status_title.setText("ENGINE OFFLINE")
            self.status_title.setStyleSheet("color:#F72585; font-size:20px; font-weight:900; letter-spacing:1px;")
            self.status_sub.setText("Press Start to activate the tunnel.")
            self.btn_toggle.setText("START ENGINE")
            self.btn_toggle.setObjectName("btn_start")
            self.term_badge.setText("\u25CF OFFLINE")
            self.term_badge.setStyleSheet("background:rgba(247,37,133,0.24); color:#F72585; font-size:10px;"
                                          "font-weight:800; padding:5px 11px; border-radius:11px; letter-spacing:1px;")
        for w in (self.pulse, self.btn_toggle):
            w.style().unpolish(w)
            w.style().polish(w)

    def start_engine(self):
        self.ensure_config()
        self.select_nav(0)
        self.set_status(True)
        self.log_html_print("System", "========================================", color="#5A48A8")
        self.log_html_print("Kernel", "\U0001F680 Initializing Shade Core...", color="#C77DFF")

        # Run the engine in the SAME executable using the hidden --engine flag.
        if getattr(sys, "frozen", False):
            program = sys.executable
            args = ["--engine"]
        else:
            program = sys.executable
            entry = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shade_engine.py")
            args = ["-u", entry, "--engine"]

        # Ensure the child works from the folder that holds config.json.
        self.process.setWorkingDirectory(app_dir())
        self.process.start(program, args)

    def stop_engine(self):
        self.log_html_print("System", "Terminating engine...", color="#F72585")
        self.process.kill()
        self.process.waitForFinished(1500)

    def process_finished(self):
        self.set_status(False)
        self.log_html_print("System", "Engine and network hooks released.", color="#CAC0EC")

    # ======================================================
    #  Log handling
    # ======================================================
    def handle_stdout(self):
        data = self.process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        for line in data.splitlines():
            self.process_incoming_log(line)

    def handle_stderr(self):
        data = self.process.readAllStandardError().data().decode("utf-8", errors="replace")
        for line in data.splitlines():
            self.process_incoming_log(line)

    def process_incoming_log(self, text):
        text = text.strip()
        if not text:
            return

        if "WinError 6" in text or "The handle is invalid" in text:
            self.log_html_print("Kernel", "WinDivert engine active \u2014 injecting packets \U0001F7E2", color="#00F5D4")
            return

        lower = text.lower()
        is_error = any(w in text for w in ("Error", "Exception", "Traceback", "raise "))

        if not self.is_debug_mode:
            junk = ["File \"", "line ", "Traceback", "During handling",
                    "self._ov", "future:", "Task ", "Cancel", "^^", "~~", "await "]
            if any(w in text for w in junk):
                return
            # Keep real ERROR: messages visible even with debug off.
            if is_error and not text.startswith("ERROR"):
                return

        if is_error:
            self.log_html_print("Backend", text, color="#F72585")
        elif "active" in lower or "ready" in lower or "listening" in lower:
            self.log_html_print("Core", text, color="#00F5D4")
        else:
            self.log_html_print("Core", text, color="#EAE4FC")

    def log_html_print(self, prefix, message, color="#EAE4FC"):
        time_str = time.strftime("%H:%M:%S")
        html = f"""
        <div style="margin-bottom:4px;">
            <span style="color:#A99CD8; font-size:12px;">[{time_str}]</span>
            <span style="color:#9D4EDD; font-weight:bold; font-size:14px;">\u276F</span>
            <span style="color:#C77DFF; font-weight:bold; font-size:13px;">{prefix}</span>
            <span style="color:{color}; font-size:13px;">{message}</span>
        </div>
        """
        self.terminal.append(html)
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.terminal.setTextCursor(cursor)

    def closeEvent(self, event):
        if self.process.state() == QProcess.ProcessState.Running:
            self.process.kill()
            self.process.waitForFinished(1000)
        event.accept()


def build_dark_palette() -> QPalette:
    """Dark palette applied app-wide.

    Qt's "Fusion" style paints unstyled widgets with the default light/grey
    palette, which used to leave grey rectangles behind cards, scroll areas,
    stacked pages and dialogs. Forcing a dark palette guarantees that anything
    the stylesheet does not explicitly cover still renders dark.
    """
    base = QColor("#171130")
    surface = QColor("#211A45")
    text = QColor("#F4F1FE")
    muted = QColor("#BFB3E6")
    accent = QColor("#7B2CBF")

    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, base)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, surface)
    p.setColor(QPalette.ColorRole.AlternateBase, base)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.PlaceholderText, muted)
    p.setColor(QPalette.ColorRole.Button, surface)
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.ToolTipBase, surface)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Highlight, accent)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    p.setColor(QPalette.ColorRole.Link, QColor("#C77DFF"))
    p.setColor(QPalette.ColorRole.LinkVisited, QColor("#9D4EDD"))
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled):
        p.setColor(group, QPalette.ColorRole.Window, base)
        p.setColor(group, QPalette.ColorRole.Base, surface)
        p.setColor(group, QPalette.ColorRole.Button, surface)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, muted)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, muted)
    return p


def run_gui():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Bitologist.ShadeEngine.GUI.1")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(load_app_icon())

    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app.setStyle("Fusion")
    app.setPalette(build_dark_palette())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
