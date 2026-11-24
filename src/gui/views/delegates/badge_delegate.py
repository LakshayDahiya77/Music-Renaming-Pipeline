"""Custom QStyledItemDelegate for rendering colored badges and status pills."""

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from gui.common.theme import DARK_THEME

class BadgeDelegate(QStyledItemDelegate):
    """Renders confidence, resolution, and validation status values as rounded colored pill badges."""

    COLORS = {
        # Confidence colors
        "high": (QColor("#1e3322"), QColor(DARK_THEME["success"])),     # Dark green bg, #4caf50 text
        "medium": (QColor("#3d3314"), QColor(DARK_THEME["warning"])),   # Dark amber bg, #ffc107 text
        "low": (QColor("#3d1c1c"), QColor(DARK_THEME["error"])),        # Dark red bg, #f44336 text
        # Status colors
        "ready": (QColor("#1e3322"), QColor(DARK_THEME["success"])),    # #4caf50
        "modified": (QColor("#182b3d"), QColor(DARK_THEME["accent"])),  # #62a0ea
        "review": (QColor("#3d3314"), QColor(DARK_THEME["warning"])),   # #ffc107
        "collision": (QColor("#3d1c1c"), QColor(DARK_THEME["error"])),  # #f44336
        "illegal": (QColor("#450a0a"), QColor("#ff5346")),              # Dark red bg, bright red text
        "excluded": (QColor("#242629"), QColor(DARK_THEME["text_secondary"])), # #a0a0a0
        # Resolution colors
        "2160p": (QColor("#3b1b4d"), QColor("#c084fc")),                # Purple
        "1440p": (QColor("#182b3d"), QColor(DARK_THEME["accent"])),     # Accent #62a0ea
        "1080p": (QColor("#1e3322"), QColor(DARK_THEME["success"])),    # Success #4caf50
        "720p": (QColor("#3d3314"), QColor(DARK_THEME["warning"])),     # Warning #ffc107
        "540p": (QColor("#3d2514"), QColor("#fb923c")),                 # Orange
        "480p": (QColor("#3d1c1c"), QColor(DARK_THEME["error"])),       # Error #f44336
        "360p": (QColor("#242629"), QColor(DARK_THEME["text_secondary"])), # Gray #a0a0a0
        "unknown": (QColor("#282a2e"), QColor(DARK_THEME["text_secondary"])), # Muted gray pill
    }

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "").strip()
        key = text.lower()

        if key in self.COLORS:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            if option.state & QStyle.StateFlag.State_Selected:
                painter.fillRect(option.rect, option.palette.highlight())

            bg_color, fg_color = self.COLORS[key]

            font = QFont(option.font)
            font.setBold(True)
            if font.pixelSize() > 0:
                font.setPixelSize(max(12, font.pixelSize() - 1))
            elif font.pointSize() > 0:
                font.setPointSize(max(9, font.pointSize()))
            else:
                font.setPixelSize(12)
            painter.setFont(font)

            metrics = painter.fontMetrics()
            text_width = metrics.horizontalAdvance(text)
            badge_width = max(text_width + 12, 48)
            badge_height = max(18, min(option.rect.height() - 6, 20))

            rect = option.rect
            x = rect.x() + (rect.width() - badge_width) / 2
            y = rect.y() + (rect.height() - badge_height) / 2
            badge_rect = QRectF(x, y, badge_width, badge_height)

            path = QPainterPath()
            path.addRoundedRect(badge_rect, 5, 5)
            painter.fillPath(path, bg_color)
            painter.setPen(fg_color)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)

            painter.restore()
        else:
            super().paint(painter, option, index)
