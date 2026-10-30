import base64
import io
import json
import os
import uuid
from collections import defaultdict

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request, send_file
from flask import url_for
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
WORK_DIR = os.path.join(BASE_DIR, "work")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

SESSIONS = {}


@app.route("/")
def index():
    return render_template("index.html")


def _binarize(img_bgr, blocksize, c, invert=False):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 3)
    bs = max(3, int(blocksize) // 2 * 2 + 1)
    # pixels > (local mean - c) become white (letters)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    if invert:
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, bs, float(c))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        return binary
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                  cv2.THRESH_BINARY_INV, bs, float(c))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    return binary


def _sorted_contours(binary):
    contours, hierarchy = cv2.findContours(
        binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hierarchy is None:
        return []
    hierarchy = hierarchy[0]
    # keep contours that have at least area and depth 0 (outer) or 1 (hole)
    kept = []
    for i, cnt in enumerate(contours):
        area = cv2.contourArea(cnt)
        if area < 40:
            continue
        kept.append((i, cnt, hierarchy[i][3], area))
    return kept


def _approx(contour, epsilon):
    if epsilon <= 0:
        return contour
    peri = cv2.arcLength(contour, True)
    ap = cv2.approxPolyDP(contour, epsilon * peri, True)
    return ap if len(ap) >= 3 else contour


def _svg_path_from_contours(contours, epsilon, tx=0.0, ty=0.0, sx=1.0, sy=1.0):
    parts = []
    for cnt in contours:
        ap = _approx(cnt, epsilon)
        pts = ap.reshape(-1, 2).astype(float)
        pts[:, 0] = (pts[:, 0] + tx) * sx
        pts[:, 1] = (pts[:, 1] + ty) * sy
        if len(pts) < 3:
            continue
        d = "M "
        d += " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts)
        d += " Z"
        parts.append(d)
    return " ".join(parts)


def _group_glyphs(contour_list, gap_ratio):
    """Group outer contours + their holes into glyphs."""
    outers = [(i, cnt, area) for i, cnt, parent, area in contour_list if parent == -1]
    if not outers:
        return []
    boxes = []
    for i, cnt, area in outers:
        x, y, w, h = cv2.boundingRect(cnt)
        boxes.append({"idx": i, "x": x, "y": y, "w": w, "h": h})
    heights = sorted(b["h"] for b in boxes)
    median_h = heights[len(heights) // 2] or 1
    gap = median_h * float(gap_ratio)
    boxes.sort(key=lambda b: b["x"])
    merged = []
    for b in boxes:
        placed = False
        for m in merged:
            x_overlap = (b["x"] < m["x"] + m["w"] + gap and
                         b["x"] + b["w"] + gap > m["x"])
            y_overlap = (b["y"] < m["y"] + m["h"] and
                         b["y"] + b["h"] > m["y"])
            if x_overlap and y_overlap:
                nx = min(m["x"], b["x"])
                ny = min(m["y"], b["y"])
                x2 = max(m["x"] + m["w"], b["x"] + b["w"])
                y2 = max(m["y"] + m["h"], b["y"] + b["h"])
                m["x"], m["y"], m["w"], m["h"] = nx, ny, x2 - nx, y2 - ny
                m["members"].append(b["idx"])
                placed = True
                break
        if not placed:
            merged.append({"x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"],
                           "members": [b["idx"]]})
    merged.sort(key=lambda m: (int((m["y"] + m["h"] / 2) / max(1, median_h * 0.9)), m["x"]))
    return merged


def _extract_glyphs(img_bgr, blocksize, c, epsilon, gap_ratio, min_area,
                    invert=False):
    binary = _binarize(img_bgr, blocksize, c, invert)
    contour_list = []
    contours, hierarchy = cv2.findContours(
        binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hierarchy is None:
        return [], binary
    hierarchy = hierarchy[0]
    img_w = binary.shape[1]
    img_h = binary.shape[0]
    for i, cnt in enumerate(contours):
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        if hierarchy[i][3] == -1 and (w > img_w * 0.4 or h > img_h * 0.4):
            continue
        contour_list.append((i, cnt, hierarchy[i][3], area))
    glyphs = _group_glyphs(contour_list, gap_ratio)
    result = []
    for m in merged_to_glyphs(glyphs, contour_list):
        result.append(m)
    # attach paths
    for g in result:
        outer_idx = g["members"]
        holes = []
        for i, cnt, parent, area in contour_list:
            if parent in outer_idx:
                holes.append(cnt)
        outer_cnts = [cnt for i, cnt, parent, area in contour_list if i in outer_idx]
        x, y, w, h = g["x"], g["y"], g["w"], g["h"]
        path = _svg_path_from_contours(outer_cnts + holes, epsilon, tx=-x, ty=-y)
        result_paths = {
            "path": path,
            "w": w, "h": h,
            "x": x, "y": y,
            "id": str(uuid.uuid4())[:8],
        }
        g.update(result_paths)
        g["label"] = ""
    return result, binary


def merged_to_glyphs(merged, contour_list):
    return merged


def _glyph_preview_png(binary, box, pad=6):
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(binary.shape[1], x + w + pad)
    y1 = min(binary.shape[0], y + h + pad)
    roi = binary[y0:y1, x0:x1]
    vis = 255 - roi  # black letter on white
    pil = Image.fromarray(vis)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "Kein Bild erhalten"}), 400
    data = np.frombuffer(file.read(), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify({"error": "Bild konnte nicht gelesen werden"}), 400
    if max(img.shape[:2]) > 2200:
        scale = 2200 / max(img.shape[:2])
        img = cv2.resize(img, None, fx=scale, fy=scale)
    params = {k: float(request.form.get(k, v)) for k, v in {
        "blocksize": 31, "c": 10, "epsilon": 0.002, "gap_ratio": 0.05,
        "min_area": 40}.items()}
    invert = request.form.get("invert") in ("on", "1", "true")
    crop = request.form.get("crop")  # "x,y,w,h" in original image coords
    if crop:
        try:
            cx, cy, cw, ch = [int(float(v)) for v in crop.split(",")]
            img = img[max(0, cy):cy + ch, max(0, cx):cx + cw]
        except ValueError:
            pass
    glyphs, binary = _extract_glyphs(
        img, int(params["blocksize"]), params["c"], params["epsilon"],
        params["gap_ratio"], int(params["min_area"]), invert)
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"glyphs": glyphs, "labels": {}}
    for g in glyphs:
        g["preview"] = _glyph_preview_png(binary, g)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    full_preview = "data:image/jpeg;base64," + base64.b64encode(buf).decode()
    return jsonify({
        "session": sid,
        "full": full_preview,
        "fullW": int(img.shape[1]),
        "fullH": int(img.shape[0]),
        "count": len(glyphs),
        "glyphs": [
            {"id": g["id"], "preview": g["preview"], "w": g["w"], "h": g["h"]}
            for g in glyphs]})


def _find_font():
    for p in ["/usr/share/fonts", "/System/Library/Fonts", "C:/Windows/Fonts"]:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in files:
                    if f.lower().endswith(".ttf"):
                        return os.path.join(root, f)
    return None


@app.route("/label", methods=["POST"])
def label():
    data = request.get_json(force=True)
    sid = data.get("session")
    labels = data.get("labels", {})
    if sid not in SESSIONS:
        return jsonify({"error": "Session unbekannt"}), 400
    SESSIONS[sid]["labels"] = labels
    return jsonify({"ok": True, "labeled": len(labels)})


@app.route("/compose", methods=["POST"])
def compose():
    data = request.get_json(force=True)
    sid = data.get("session")
    text = data.get("text", "")
    spacing = float(data.get("spacing", 1.0))
    size = float(data.get("size", 100))
    line_spacing = float(data.get("line_spacing", 1.4))
    if sid not in SESSIONS:
        return jsonify({"error": "Session unbekannt"}), 400
    sess = SESSIONS[sid]
    by_label = {}
    for g in sess["glyphs"]:
        lab = sess["labels"].get(g["id"], "")
        for ch in lab:
            if ch != " ":
                by_label.setdefault(ch, g)
    if not by_label:
        return jsonify({"error": "Bitte zuerst Glyphen beschriften"}), 400
    # SVG aufbauen
    cur_x = 0.0
    cur_y = 0.0
    line_h = max(g["h"] for g in by_label.values())
    body = []
    missing = []
    for i, ch in enumerate(text):
        if ch == "\n" or ch == " ":
            if ch == " ":
                g = by_label.get("space") or None
                sw = (g["w"] if g else line_h * 0.35) * (size / max(line_h, 1))
                cur_x += sw * spacing + size * 0.06
            if ch == "\n":
                cur_x = 0.0
                cur_y += size * line_spacing
            continue
        g = by_label.get(ch)
        if g is None:
            missing.append(ch)
            cur_x += size * 0.5 * spacing
            continue
        scale = size / max(g["h"], 1)
        body.append(
            f'<path transform="translate({cur_x:.2f} {cur_y:.2f}) '
            f'scale({scale:.5f})" d="{g["path"]}"/>')
        cur_x += g["w"] * scale * spacing + size * 0.06
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size*12:.0f}" '
        f'height="{size*2*line_spacing + size:.0f}" viewBox="0 0 {size*12:.0f} '
        f'{size*2*line_spacing + size:.0f}">\n'
        f'<g fill="#000000" fill-rule="evenodd">\n' + "\n".join(body) +
        "\n</g>\n</svg>")
    resp = send_file(io.BytesIO(svg.encode("utf-8")), mimetype="image/svg+xml",
                     as_attachment=True, download_name="text.svg")
    if missing:
        resp.headers["X-Missing-Chars"] = ",".join(sorted(set(missing)))
    return resp


@app.route("/font_svg", methods=["POST"])
def font_svg():
    data = request.get_json(force=True)
    sid = data.get("session")
    if sid not in SESSIONS:
        return jsonify({"error": "Session unbekannt"}), 400
    sess = SESSIONS[sid]
    size = 100.0
    x = 0.0
    y = 0.0
    body = []
    for g in sess["glyphs"]:
        lab = sess["labels"].get(g["id"], "?")
        scale = size / max(g["h"], 1)
        body.append(
            f'<path transform="translate({x:.2f} {y:.2f}) '
            f'scale({scale:.5f})" d="{g["path"]}"/>')
        x += g["w"] * scale + size * 0.3
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{x+size:.0f}" '
        f'height="{size*1.5:.0f}" viewBox="0 0 {x+size:.0f} {size*1.5:.0f}">\n'
        f'<g fill="#000000" fill-rule="evenodd">\n' + "\n".join(body) +
        "\n</g>\n</svg>")
    return send_file(io.BytesIO(svg.encode("utf-8")), mimetype="image/svg+xml",
                     as_attachment=True, download_name="glyphs.svg")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
