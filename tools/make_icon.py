"""App icon: red rounded 'play button' shape with a white download arrow, transparent background.
Drawn as vectors (measured from the reference image), so every size is sharp."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPointF as P
app = QtWidgets.QApplication([])
RED, WHITE = QtGui.QColor("#FF0000"), QtGui.QColor("#FFFFFF")
x0, x1, y0, y1 = 402.0, 1645.0, 554.0, 1493.0          # body in the 2048 reference
r, bt, bs, k = 230.0, 10.0, 13.0, 0.5523


def body():
    p = QtGui.QPainterPath()
    p.moveTo(x0 + r, y0 + bt)
    p.quadTo(P((x0 + x1) / 2, y0 - bt), P(x1 - r, y0 + bt))                           # top, slightly convex
    p.cubicTo(P(x1 - r + r * k, y0 + bt), P(x1 - bs, y0 + r - r * k), P(x1 - bs, y0 + r))
    p.quadTo(P(x1 + bs, (y0 + y1) / 2), P(x1 - bs, y1 - r))                           # right side
    p.cubicTo(P(x1 - bs, y1 - r + r * k), P(x1 - r + r * k, y1 - bt), P(x1 - r, y1 - bt))
    p.quadTo(P((x0 + x1) / 2, y1 + bt), P(x0 + r, y1 - bt))                           # bottom
    p.cubicTo(P(x0 + r - r * k, y1 - bt), P(x0 + bs, y1 - r + r * k), P(x0 + bs, y1 - r))
    p.quadTo(P(x0 - bs, (y0 + y1) / 2), P(x0 + bs, y0 + r))                           # left side
    p.cubicTo(P(x0 + bs, y0 + r - r * k), P(x0 + r - r * k, y0 + bt), P(x0 + r, y0 + bt))
    p.closeSubpath()
    return p


def glyph():
    cx = (x0 + x1) / 2
    arrow = QtGui.QPainterPath()
    arrow.addRoundedRect(QtCore.QRectF(cx - 51.5, 752, 103, 260), 12, 12)               # shaft
    head = QtGui.QPainterPath()
    head.addPolygon(QtGui.QPolygonF([P(cx - 156, 995), P(cx + 156, 995), P(cx, 1128)]))
    head.closeSubpath()
    head = QtGui.QPainterPathStroker(QtGui.QPen(WHITE, 16, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap,
                                                QtCore.Qt.PenJoinStyle.RoundJoin)).createStroke(head).united(head)
    arrow = arrow.united(head)
    # tray (U): outer 756–1291 × 1136–1293, arms 59 wide, bottom 48 thick, round outer bottom corners
    L, R, T, B, a, b, rr = 756.0, 1291.0, 1136.0, 1293.0, 59.0, 48.0, 30.0
    u = QtGui.QPainterPath()
    u.moveTo(L + 8, T)
    u.lineTo(L + a - 8, T)
    u.quadTo(P(L + a, T), P(L + a, T + 8))
    u.lineTo(L + a, B - b)
    u.lineTo(R - a, B - b)
    u.lineTo(R - a, T + 8)
    u.quadTo(P(R - a, T), P(R - a + 8, T))
    u.lineTo(R - 8, T)
    u.quadTo(P(R, T), P(R, T + 8))
    u.lineTo(R, B - rr)
    u.quadTo(P(R, B), P(R - rr, B))
    u.lineTo(L + rr, B)
    u.quadTo(P(L, B), P(L, B - rr))
    u.lineTo(L, T + 8)
    u.quadTo(P(L, T), P(L + 8, T))
    u.closeSubpath()
    return arrow.united(u)


def render(size, fill=0.94):
    img = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    s = size * fill / (x1 - x0)
    p.translate(size / 2, size / 2)
    p.scale(s, s)
    p.translate(-(x0 + x1) / 2, -(y0 + y1) / 2)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(RED)
    p.drawPath(body())
    p.setBrush(WHITE)
    p.drawPath(glyph())
    p.end()
    return img


out = sys.argv[1]
render(1024).save(f"{out}/icon_1024.png")
render(256).save(f"{out}/icon_256.png")
print("ok")
