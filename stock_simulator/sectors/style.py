from pathlib import Path


STYLE = '''
QWidget#SectorPage { background: #101214; color: #ced1d5; }
QLabel#SectorHeading { font-size: 15px; font-weight: 500; color: #d9dcdf; }
QLabel#SectorDateLabel { font-size: 15px; font-weight: 600; color: #e0e5e9; }
QLabel#SectorNotice { color: #a89e86; padding: 4px; background: #1a1c1f; }
QLabel#SectorDateWarning { color: #ffc56e; padding: 5px 7px; background: #2b2115; border: 1px solid #6b4a1f; border-radius: 4px; }
QTableWidget { background: #111416; alternate-background-color: #171a1d; color: #cbd0d5;
    border: 1px solid #2a2e32; gridline-color: #24282c; selection-background-color: #30383e; }
QHeaderView::section { background: #1d2125; color: #a7afb7; padding: 5px; border: 0; }
QTableWidget::item { padding: 2px; }
QLineEdit, QDateEdit, QComboBox { background: #181c20; color: #d2d6db; border: 1px solid #343a40; padding: 5px; border-radius: 3px; }
QDateEdit { font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 15px; }
QPushButton { background: #20252a; color: #cbd1d7; border: 1px solid #373e44; padding: 5px 11px; border-radius: 3px; }
QPushButton:hover { background: #2b3238; }
QPushButton:disabled { background: #1b2024; color: #646c73; border-color: #2a2e32; }
QPushButton#SectorTrain { background: #35434d; color: #e0e5e8; font-weight: 500; }
QPushButton#SectorTrain:hover { background: #46606f; color: #ffffff; border-color: #6b8799; }
QPushButton#SectorTrain:pressed { background: #2b3740; }
QPushButton#SectorTrain:disabled { background: #20252a; color: #646c73; border-color: #2a2e32; }
QTabBar::tab { background: #181c20; color: #979fa7; padding: 5px 12px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { background: #292f34; color: #d2d9df; border-bottom: 2px solid #899ba8; }
QSplitter::handle { background: #292e33; }
QPushButton#SectorBackButton { background: #24405a; color: #cfe6f7; border: 1px solid #4d7ea8;
    font-weight: 600; }
QPushButton#SectorBackButton:hover { background: #2f5a7d; border-color: #7db4d8; color: #ffffff; }
QPushButton#SectorBackButton:pressed { background: #1b3247; }
QPushButton#SectorBackButton:disabled { background: #1b2024; color: #646c73; border-color: #2a2e32; }
QCheckBox { color: #cbd1d7; spacing: 5px; }
QCheckBox::indicator { width: 12px; height: 12px; border: 1px solid #3b4249;
    border-radius: 3px; background: #181c20; }
QCheckBox::indicator:hover { border-color: #6b8799; }
QCheckBox::indicator:checked { background: #4d6b80; border-color: #6b8799; }
QCheckBox::indicator:checked:hover { background: #5d8199; }
QTableWidget QScrollBar:vertical { width: 5px; background: #131619; border: none; margin: 0; }
QTableWidget QScrollBar:horizontal { height: 5px; background: #131619; border: none; margin: 0; }
QTableWidget QScrollBar::handle:vertical { background: #4a535b; min-height: 28px; border-radius: 2px; }
QTableWidget QScrollBar::handle:horizontal { background: #4a535b; min-width: 28px; border-radius: 2px; }
QTableWidget QScrollBar::handle:hover { background: #697782; }
QTableWidget QScrollBar::add-line, QTableWidget QScrollBar::sub-line { width: 0; height: 0; border: none; background: transparent; }
QTableWidget QScrollBar::add-page, QTableWidget QScrollBar::sub-page { background: transparent; }
QTableWidget QTableCornerButton::section { background: #131619; border: none; }
'''

# 勾选态画一个对勾（浅蓝色，不是白色）：QSS 只能靠图片。
_CHECK_ICON = (Path(__file__).resolve().parents[1] / 'assets' / 'check.svg').as_posix()
STYLE = STYLE + (
    "\nQCheckBox::indicator:checked { image: url(%s); }" % _CHECK_ICON
    + "\nQCheckBox::indicator:checked:hover { image: url(%s); }" % _CHECK_ICON
)

NAV_STYLE = '''
QWidget#SectorNavigation { background: #131619; border-bottom: 1px solid #2b3035; }
QPushButton { border: none; border-bottom: 2px solid transparent; border-radius: 0;
    background: transparent; color: #969fa7; min-height: 0px;
    padding: 2px 16px; font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 13px; font-weight: 500; }
QPushButton:hover { background: #242a2f; color: #d6dce1; }
QPushButton:checked { background: #262d32; color: #e0e5e9; border-bottom: 2px solid #8c9eab; }
QLabel#SectorClock { color: #b7bfc6; padding: 2px 5px 2px 10px;
    font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 13px; font-weight: 400; }
QLabel#SectorPhase { color: #aeb9c1; background: #252c31; border: 1px solid #343c43;
    border-radius: 4px; margin: 4px 6px 4px 0px; padding: 0px 6px;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 11px; font-weight: 400; }
'''

CALENDAR_STYLE = '''
QCalendarWidget { background: #111c2b; color: #dce7f5;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 14px; }
QCalendarWidget QWidget#qt_calendar_navigationbar { background: #18283d; padding: 7px; }
QCalendarWidget QToolButton { color: #dce7f5; background: transparent; border: none;
    border-radius: 5px; padding: 5px 10px; font-size: 15px; font-weight: 500; }
QCalendarWidget QToolButton:hover { background: #294566; }
QCalendarWidget QToolButton::menu-indicator { width: 0px; }
QCalendarWidget QToolButton#qt_calendar_prevmonth,
QCalendarWidget QToolButton#qt_calendar_nextmonth { font-size: 24px; padding: 0px 10px; }
QCalendarWidget QAbstractItemView { background: #111c2b; alternate-background-color: #162337;
    color: #dce7f5; selection-background-color: #2b71be; selection-color: #ffffff;
    border: none; outline: none; font-size: 14px; }
QCalendarWidget QMenu { background: #18283d; color: #dce7f5; border: 1px solid #30465f; }
QCalendarWidget QMenu::item { padding: 6px 18px; }
QCalendarWidget QMenu::item:selected { background: #2b527c; }
QCalendarWidget QSpinBox { background: #111c2b; color: #dce7f5; border: 1px solid #3c628a;
    padding: 3px 6px; selection-background-color: #2b71be; }
'''
