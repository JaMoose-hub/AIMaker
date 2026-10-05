"""Standalone photo annotation POC; original pixels, editable region IDs, no cloud calls.

Requires Pillow. Optional --detect reuses the existing Pi 5 ONNX/profile pipeline.
The viewer is an offline HTML file; all source images are embedded as PNG.
"""
from __future__ import annotations

import argparse
import base64
import colorsys
import hashlib
import io
import json
import math
from pathlib import Path
from collections import Counter

from PIL import Image, ImageCms, ImageDraw, ImageFont, ImageOps

HERE = Path(__file__).resolve().parent
VERSION = 1
COLOR_LABELS = {
    "red": "紅色", "orange": "橘色", "yellow": "黃色", "green": "綠色",
    "blue": "藍色", "purple": "紫色", "black": "黑色", "white": "白色",
    "gray": "灰色", "unknown": "未知",
    "pink": "粉紅色", "brown": "棕色", "multicolor": "多色", "other": "其他",
}
CYAN = (0, 142, 194)
WIRE_DISPLAY_COLORS = {"red": (215, 37, 53), "orange": (226, 105, 12),
                       "yellow": (196, 154, 0), "green": (0, 139, 94),
                       "blue": (25, 83, 208), "purple": (139, 67, 175),
                       "pink": (216, 67, 137), "brown": (135, 85, 48),
                       "black": (22, 25, 29), "white": (180, 186, 196),
                       "gray": (107, 114, 128), "unknown": (107, 114, 128),
                       "other": (107, 114, 128), "multicolor": (107, 114, 128)}


def validate_cloud_observation(value, size):
    if not isinstance(value, dict) or value.get("wire_color") not in COLOR_LABELS:
        raise ValueError("雲端線色觀察格式錯誤")
    if value.get("visibility") not in {"clear", "partial", "uncertain"}:
        raise ValueError("雲端可見性格式錯誤")
    roi = value.get("wire_roi")
    if roi is not None:
        keys = ("x_min", "y_min", "x_max", "y_max")
        if not isinstance(roi, dict) or any(isinstance(roi.get(k), bool) or
                not isinstance(roi.get(k), (float, int)) or not math.isfinite(roi[k]) for k in keys):
            raise ValueError("雲端線材區域必須為有限座標")
        if not (0 <= roi["x_min"] < roi["x_max"] < size[0] and
                0 <= roi["y_min"] < roi["y_max"] < size[1]):
            raise ValueError("雲端線材區域超界或方向錯誤")
        roi = {k: float(roi[k]) for k in keys}
    output = {"wire_color": value["wire_color"], "visibility": value["visibility"], "wire_roi": roi}
    for key, limit in (("evidence", 1000), ("model", 150), ("effort", 20)):
        if not isinstance(value.get(key), str) or not 0 < len(value[key]) <= limit:
            raise ValueError("雲端觀察文字格式錯誤")
        output[key] = value[key]
    return output


def font(size: int, bold: bool = False):
    paths = [Path("C:/Windows/Fonts") / ("msjhbd.ttc" if bold else "msjh.ttc"),
             Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for path in paths:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def load_photo(path: Path) -> Image.Image:
    with Image.open(path) as image:
        original_profile = image.info.get("icc_profile")
        oriented = ImageOps.exif_transpose(image).convert("RGB")
        if original_profile:
            try:
                oriented = ImageCms.profileToProfile(
                    oriented, ImageCms.ImageCmsProfile(io.BytesIO(original_profile)),
                    ImageCms.createProfile("sRGB"), outputMode="RGB",
                )
            except (OSError, ValueError, ImageCms.PyCMSError) as error:
                raise ValueError(f"照片色彩設定無法轉成 sRGB：{path.name}") from error
        oriented.info.clear()
        oriented.info["poc_color_management"] = "ICC converted to sRGB" if original_profile else "RGB interpreted as sRGB"
        return oriented


def classify_rgb(rgb):
    h, s, v = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
    hue = h * 360
    if v < .17:
        return "black"
    if s < .16:
        return "white" if v > .82 else "gray"
    if s < .28 or v < .28:
        return "unknown"
    if hue < 15 or hue >= 345:
        return "red"
    if hue < 40:
        return "orange"
    if hue < 72:
        return "yellow"
    if hue < 175:
        return "green"
    if hue < 265:
        return "blue"
    return "purple"


def sample_color(image: Image.Image, x: float, y: float):
    """Local HSV patch vote, not a connector/wire detection or continuity verdict."""
    radius = max(3, round(min(image.size) * .002))
    box = (max(0, round(x) - radius), max(0, round(y) - radius),
           min(image.width, round(x) + radius + 1), min(image.height, round(y) + radius + 1))
    patch = image.crop(box)
    pixels = list(patch.get_flattened_data() if hasattr(patch, "get_flattened_data") else patch.getdata())
    votes = Counter(classify_rgb(rgb) for rgb in pixels)
    name, count = votes.most_common(1)[0]
    support = count / len(pixels)
    if support < .60:
        name = "unknown"
    selected = [rgb for rgb in pixels if classify_rgb(rgb) == name] or pixels
    rgb = [round(sum(p[channel] for p in selected) / len(selected)) for channel in range(3)]
    return dict(name=name, label=COLOR_LABELS[name], rgb=rgb, support=round(support, 3),
                method="local_hsv_vote", warning="局部色票，不證明腳號、插接或導通")


def validate_markers(markers, size):
    if not isinstance(markers, list) or len(markers) > 40:
        raise ValueError("markers 必須是最多 40 個項目的陣列")
    width, height = size
    result, seen = [], set()
    for item in markers:
        if not isinstance(item, dict):
            raise ValueError("標記格式錯誤")
        label = item.get("id")
        if (not isinstance(label, str) or not label or len(label) > 24 or label in seen
                or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for char in label)):
            raise ValueError("標記 ID 必須唯一且為 1–24 字元")
        seen.add(label)
        x, y = item.get("x"), item.get("y")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in (x, y)) or not (0 <= x < width and 0 <= y < height):
            raise ValueError(f"{label}: 座標必須位於 {width}×{height} 原圖內")
        pin = item.get("physical_pin")
        if pin is not None and (type(pin) is not int or not 1 <= pin <= 40):
            raise ValueError("physical_pin 必須是 null 或 1–40 的整數")
        reviewed = item.get("reviewed", False)
        if type(reviewed) is not bool or (reviewed and pin is None):
            raise ValueError("人工核對腳號必須同時提供有效的實體 Pin")
        source = item.get("source", "manual")
        if not isinstance(source, str) or len(source) > 60:
            raise ValueError("source 必須是最多 60 字元的字串")
        marker = dict(id=label, x=float(x), y=float(y), physical_pin=pin,
                      reviewed=reviewed, source=source)
        if source == "cloud_vision_joint" and "cloud_observation" not in item:
            raise ValueError("雲端標記缺少聯合判讀觀察")
        if "cloud_observation" in item:
            marker["cloud_observation"] = validate_cloud_observation(item["cloud_observation"], size)
        result.append(marker)
    return result


def demo_markers(size, number):
    """Hand-placed region seeds for these two user photos; every pin stays unknown."""
    seeds = ({"A": (.677, .1784), "B": (.679, .228), "C": (.665, .302)}
             if number == 0 else {"A": (.730, .373), "B": (.687, .387), "C": (.550, .386)})
    return [dict(id=label, x=round(nx * size[0]), y=round(ny * size[1]),
                 physical_pin=None, reviewed=False, source="demo_seed")
            for label, (nx, ny) in seeds.items()]


def crop_box(size, point, span=420):
    width, height = size
    crop_w, crop_h = min(span, width), min(span, height)
    left = max(0, min(width - crop_w, round(point[0] - crop_w / 2)))
    top = max(0, min(height - crop_h, round(point[1] - crop_h / 2)))
    return left, top, left + crop_w, top + crop_h


def annotate(image, markers):
    target = image.copy()
    draw = ImageDraw.Draw(target)
    scale = min(image.size) / 1400
    radius, stroke = max(6, round(7 * scale)), max(2, round(2 * scale))
    label_font = font(max(19, round(21 * scale)), True)
    guard = radius + max(6, round(8 * scale))
    occupied = [(marker["x"] - guard, marker["y"] - guard,
                 marker["x"] + guard, marker["y"] + guard) for marker in markers]
    for index, marker in enumerate(markers):
        x, y = marker["x"], marker["y"]
        caption = marker["id"]
        cloud = marker.get("cloud_observation")
        color = WIRE_DISPLAY_COLORS[cloud["wire_color"]] if cloud else CYAN
        if cloud:
            caption += " " + COLOR_LABELS[cloud["wire_color"]]
        if marker["physical_pin"] is not None:
            caption += f" | Pin {marker['physical_pin']}" + ("" if marker["reviewed"] else " ?")
        bounds = draw.textbbox((0, 0), caption, font=label_font)
        tw, th = bounds[2] - bounds[0], bounds[3] - bounds[1]
        gap = max(55, round(90 * scale))
        lx = x + gap if x + gap + tw + 20 < image.width else x - gap - tw - 20
        lx = max(4, min(image.width - tw - 24, lx))
        label_h, spacing = th + 18, max(6, round(8 * scale))
        for step in [0] + [direction * n for n in range(1, 41) for direction in (-1, 1)]:
            ly = max(4, min(image.height - label_h - 4, y - label_h / 2 + step * (label_h + spacing)))
            box = (lx, ly, lx + tw + 20, ly + label_h)
            if not any(box[0] < other[2] + spacing and box[2] + spacing > other[0]
                       and box[1] < other[3] + spacing and box[3] + spacing > other[1]
                       for other in occupied):
                break
        occupied.append(box)
        line_end = (lx if lx > x else lx + tw + 20, ly + th / 2 + 8)
        draw.line([(x, y), line_end], fill="white", width=stroke + 3)
        draw.line([(x, y), line_end], fill=color, width=stroke)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline="white", width=stroke + 2)
        draw.ellipse((x - radius + 2, y - radius + 2, x + radius - 2, y + radius - 2), outline=color, width=stroke)
        draw.rounded_rectangle((lx, ly, lx + tw + 20, ly + th + 18), radius=8, fill="white", outline=color, width=stroke)
        draw.text((lx + 10, ly + 5 - bounds[1]), caption, fill=(12, 32, 48), font=label_font)
    return target


def ai_prompt(data):
    records = [{"view_id": view["id"], "sha256": view["sha256"],
                "width": view["width"], "height": view["height"],
                "regions": [{k: marker[k] for k in ("id", "x", "y", "physical_pin", "reviewed", "source")}
                            for marker in view["markers"]]}
               for view in data["images"]]
    return ("請依原圖與未調色接頭放大圖，逐一描述標記位置的線色、插入點可見性與腳號證據。\n"
            "I01、S01 等是位置 ID，不是實體腳號。畫面上的標記是程式疊加，不是實體物件。\n"
            "source=ai_visual_prelabel 表示助理先看本次照片產生位置；不是腳號判定，網頁也沒有自動分析新照片。\n"
            "physical_pin 是候選腳號；reviewed 只表示人工核對，不是獨立影像證據。\n"
            "不得直接把候選腳號、局部色票或模型投影當成觀察結果。看不清楚請回傳 unknown/null。\n"
            "同色線或跨照片相同 ID 都不能證明是同一條線；需要實際可追蹤的線路。\n"
            "請回傳 JSON: {results:[{view_id,region_id,wire_color,observed_physical_pin,"
            "visibility,evidence}],limitations:[]}，visibility 可為 clear/occluded/uncertain。\n"
            "不要判定電氣安全、導通或元件功能。以下只有位置提示，尚未提供 AI 的判讀答案：\n"
            + json.dumps(records, ensure_ascii=False, indent=2))


def preview(image, markers):
    sheet = Image.new("RGB", (1600, 1040), "#f2f6fa")
    draw = ImageDraw.Draw(sheet)
    draw.text((30, 18), "GPIO 照片標記 POC", font=font(36, True), fill="#142a3c")
    draw.text((32, 70), "sRGB 色彩管理・可移動標記・接頭特寫・腳號待核對", font=font(20), fill="#536575")
    marked = annotate(image, markers)
    view = ImageOps.contain(marked, (950, 866), Image.Resampling.LANCZOS)
    sheet.paste(view, (30 + (950 - view.width) // 2, 132 + (866 - view.height) // 2))
    draw.text((1020, 132), "接頭局部放大（原圖）", font=font(26, True), fill="#142a3c")
    selected = markers[0] if markers else {"x": image.width / 2, "y": image.height / 2}
    zoom = image.crop(crop_box(image.size, (selected["x"], selected["y"])))
    zoom = ImageOps.contain(zoom, (540, 380), Image.Resampling.LANCZOS)
    sheet.paste(zoom, (1020, 184))
    draw.text((1020, 595), "位置    局部色票    實體腳號", font=font(22, True), fill="#142a3c")
    for i, marker in enumerate(markers[:6]):
        pin = str(marker["physical_pin"]) if marker["physical_pin"] else "待確認"
        draw.text((1020, 640 + i * 42), f"{marker['id']:4}    {marker['sample_color']['label']}       {pin}", font=font(21), fill="#284456")
    draw.text((30, 1005), f"{len(markers)} 個位置標記，腳號待核對；保留原始照片檔，放大不新增細節。", font=font(18), fill="#596b7d")
    return sheet


def generate(image_paths, out: Path, *, markers_path=None, demo=False, detect=False, model_path=None):
    if out.exists() and any(out.iterdir()):
        raise ValueError("輸出資料夾已有檔案；請指定新的資料夾，避免覆蓋")
    out.mkdir(parents=True, exist_ok=True)
    supplied = json.loads(markers_path.read_text(encoding="utf-8")) if markers_path else None
    if supplied is not None and (not isinstance(supplied, dict) or supplied.get("version") != VERSION):
        raise ValueError("標記 JSON 版本不支援")
    data = dict(version=VERSION, purpose="photo_annotation_poc", images=[],
                cloud_called=False, geometry_verified=False)
    if supplied and isinstance(supplied.get("cloud_run"), dict):
        data["cloud_run"] = supplied["cloud_run"]
        data["cloud_called"] = supplied["cloud_run"].get("one_request") is True
    image_objects = []
    for number, path in enumerate(image_paths):
        source_bytes = path.read_bytes()
        sha = hashlib.sha256(source_bytes).hexdigest()
        source_copy = f"source-original-{number + 1}{path.suffix.lower()}"
        (out / source_copy).write_bytes(source_bytes)
        image = load_photo(path)
        image_objects.append(image)
        view_id = f"view-{number + 1}"
        name = f"照片 {number + 1}"
        if supplied is not None:
            candidates = [v for v in supplied.get("images", []) if v.get("sha256") == sha]
            if len(candidates) != 1:
                raise ValueError(f"{path.name}: JSON 與原始照片 SHA-256 不符或重複")
            entry = candidates[0]
            if (entry.get("width"), entry.get("height")) != image.size:
                raise ValueError("JSON 與照片尺寸不符")
            markers = validate_markers(entry.get("markers"), image.size)
            if isinstance(entry.get("name"), str) and 0 < len(entry["name"]) <= 100:
                name = entry["name"]
        else:
            markers = validate_markers(demo_markers(image.size, number) if demo else [], image.size)
        for marker in markers:
            marker["sample_color"] = sample_color(image, marker["x"], marker["y"])
        canonical = io.BytesIO()
        image.save(canonical, format="PNG")
        png_bytes = canonical.getvalue()
        (out / f"raw-{number + 1}.png").write_bytes(png_bytes)
        sources = {marker["source"] for marker in markers}
        annotation_method = next(iter(sources)) if sources in (
            {"ai_visual_prelabel"}, {"cloud_vision_joint"}) else "editable_position_annotations"
        row = dict(id=view_id, name=name, source_filename=path.name,
                   width=image.width, height=image.height, sha256=sha,
                   source_copy=source_copy, color_management=image.info["poc_color_management"],
                   coordinate_system="exif_transposed_srgb_pixels",
                   decoded_pixels_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
                   markers=markers, annotation_method=annotation_method,
                   runtime_prelabel_inference=False, pin_hints=[], detection={"enabled": False},
                   data_url="data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii"))
        if detect:
            try:
                from detect_candidates import detect_pin_hints
                result = detect_pin_hints(path, model_path=model_path)
                row["pin_hints"] = result["pin_hints"]
                row["detection"] = result["detection"]
            except Exception as error:
                row["detection"] = dict(enabled=True, error=str(error), warning="定位失敗，保留手動位置標記")
        annotate(image, markers).save(out / f"annotated-{number + 1}.png")
        row["crops"] = []
        for marker in markers:
            box = crop_box(image.size, (marker["x"], marker["y"]))
            filename = f"crop-{number + 1}-{len(row['crops']) + 1}.png"
            image.crop(box).save(out / filename)
            row["crops"].append(dict(region_id=marker["id"], path=filename, box=list(box), adds_detail=False))
        data["images"].append(row)
    template = (HERE / "viewer.html").read_text(encoding="utf-8")
    if template.count("__POC_DATA__") != 1:
        raise ValueError("viewer.html 必須含唯一的 __POC_DATA__ 插入位置")
    embedded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    (out / "index.html").write_text(template.replace("__POC_DATA__", embedded), encoding="utf-8")
    public = {**data, "images": [{k: v for k, v in image.items() if k != "data_url"} for image in data["images"]]}
    (out / "markers.json").write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "ai-prompt.txt").write_text(ai_prompt(data), encoding="utf-8")
    (out / "preview.png").write_bytes(_png(preview(image_objects[0], data["images"][0]["markers"])))
    return public


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, action="append", required=True, help="照片路徑；可重複最多兩張")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--markers", type=Path, help="匯入已下載的標記 JSON；核對照片雜湊與尺寸")
    parser.add_argument("--demo", action="store_true", help="僅適用本次兩張照片的 A/B/C 示範座標；無腳號確認")
    parser.add_argument("--detect", action="store_true", help="可選：既有 Pi5 ONNX 單張候選 GPIO；需 backend venv")
    parser.add_argument("--model", type=Path, help="可選：Pi5 ONNX 候選模型覆寫")
    args = parser.parse_args()
    if not 1 <= len(args.image) <= 2:
        parser.error("請提供一或兩張照片")
    if args.demo and args.markers:
        parser.error("--demo 與 --markers 不能同時使用")
    try:
        result = generate(args.image, args.out, markers_path=args.markers, demo=args.demo,
                          detect=args.detect, model_path=args.model)
    except (OSError, ValueError) as error:
        parser.exit(1, f"POC: {error}\n")
    print(f"已產生：{args.out.resolve() / 'index.html'}")
    print(f"預覽：{args.out.resolve() / 'preview.png'}")
    for image in result["images"]:
        print(f"{image['name']}: {image['width']}×{image['height']}, "
              f"標記 {len(image['markers'])} 個、候選腳位 {len(image['pin_hints'])} 個")
        if image["detection"].get("error"):
            print(f"定位資訊：{image['detection']['error']}")


if __name__ == "__main__":
    main()
