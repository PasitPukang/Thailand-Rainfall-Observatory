"""Build the provincial heavy-rain and weather page in the editable PBIP report."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from build_layout_2026 import literal, textbox


ROOT = Path(__file__).resolve().parent
PAGES = ROOT / "Thailand_Rainfall_2018_2026.Report/definition/pages"
OVERVIEW = "7c266bc4c4c4cb19068e"
TOPIC = hashlib.sha1(b"thailand-rainfall-heavy-weather-topic-page").hexdigest()[:20]
SOURCE_VISUALS = PAGES / OVERVIEW / "visuals"
TARGET_VISUALS = PAGES / TOPIC / "visuals"


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def replace_text(value, before: str, after: str):
    if isinstance(value, dict):
        return {key: replace_text(item, before, after) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_text(item, before, after) for item in value]
    if isinstance(value, str):
        return value.replace(before, after)
    return value


def title(item: dict, label: str) -> None:
    item["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"] = literal(label)


def overview_measure(visual_id: str, old: str, new: str, label: str) -> None:
    path = SOURCE_VISUALS / visual_id / "visual.json"
    item = json.loads(path.read_text(encoding="utf-8"))
    item = replace_text(item, old, new)
    title(item, label)
    save(path, item)


def clone(visual_id: str, key: str, position: tuple[int, int, int, int],
          label: str | None = None, measure: str | None = None) -> None:
    source = json.loads((SOURCE_VISUALS / visual_id / "visual.json").read_text(encoding="utf-8"))
    item = copy.deepcopy(source)
    if measure:
        old = "Rainfall per point (mm)" if source["visual"]["visualType"] == "lineChart" else "Heavy Days per point"
        item = replace_text(item, old, measure)
    new_id = hashlib.sha1(f"thailand-rainfall-topic-{key}".encode()).hexdigest()[:20]
    item["name"] = new_id
    x, y, width, height = position
    item["position"].update(x=x, y=y, width=width, height=height, tabOrder=y)
    if label:
        title(item, label)
    save(TARGET_VISUALS / new_id / "visual.json", item)


def add_text(key: str, content: str, position: tuple[int, int, int, int],
             size: str, color: str, bold: bool = False) -> None:
    new_id = hashlib.sha1(f"thailand-rainfall-topic-{key}".encode()).hexdigest()[:20]
    save(TARGET_VISUALS / new_id / "visual.json",
         textbox(new_id, content, *position, size, color, bold))


def main() -> None:
    overview_measure("fd314105e6033b0ab04c", "Heavy Rain Days", "Heavy Days per point",
                     "วันฝนหนัก · เฉลี่ยต่อจุด")
    overview_measure("bd90e7e838e2580d0522", "Very Heavy Rain Days", "Very Heavy Days per point",
                     "วันฝนหนักมาก · เฉลี่ยต่อจุด")
    overview_measure("f7f6c2ea257addc830eb", "Total Rainfall (mm)", "Rainfall per point (mm)",
                     "ฝนสะสม · เฉลี่ยต่อจุด")
    overview_measure("e4bdfbc86070ecc30b70", "Total Rainfall (mm)", "Rainfall per point (mm)",
                     "ฝนสะสมเฉลี่ยต่อจุดรายปี | 2026 ยังไม่ครบปี")

    page = json.loads((PAGES / OVERVIEW / "page.json").read_text(encoding="utf-8"))
    page.update(name=TOPIC, displayName="แนวโน้มฝนหนักและสภาพอากาศ", width=1440, height=1100)
    save(PAGES / TOPIC / "page.json", page)
    pages_path = PAGES / "pages.json"
    pages = json.loads(pages_path.read_text(encoding="utf-8"))
    if TOPIC not in pages["pageOrder"]:
        pages["pageOrder"].append(TOPIC)
    save(pages_path, pages)

    add_text("heading", "แนวโน้มฝนตกหนักและสภาพอากาศรายจังหวัด", (40, 25, 1000, 62),
             "26pt", "#17324A", True)
    add_text("subtitle", "เลือกจังหวัดทางขวา · เมื่อเลือกทั้งหมด ตัวเลขเป็นค่าเฉลี่ยต่อจุดตัวแทน 77 จังหวัด", (42, 98, 1000, 35),
             "12pt", "#5F7789")
    clone("01aa2b481b9696865277", "province-slicer", (1040, 24, 360, 135),
          "เลือกจังหวัด")

    cards = [
        ("heavy-card", "Heavy Days per point", "วันฝนหนักต่อจุด"),
        ("very-heavy-card", "Very Heavy Days per point", "วันฝนหนักมากต่อจุด"),
        ("rain-card", "Rainfall per point (mm)", "ฝนสะสมต่อจุด (มม.)"),
        ("temperature-card", "Average Temperature (C)", "อุณหภูมิเฉลี่ย (°C)"),
        ("humidity-card", "Average Humidity (%)", "ความชื้นเฉลี่ย (%)"),
    ]
    for index, (key, measure, label) in enumerate(cards):
        clone("fd314105e6033b0ab04c", key, (40 + index * 274, 180, 258, 130),
              label, measure)

    charts = [
        ("heavy-trend", "Heavy Days per point", "วันฝนหนักรายปี · 2026 ยังไม่ครบปี", (40, 350, 660, 280)),
        ("rain-trend", "Rainfall per point (mm)", "ฝนสะสมต่อจุดรายปี · 2026 ยังไม่ครบปี", (720, 350, 680, 280)),
        ("temperature-trend", "Average Temperature (C)", "อุณหภูมิเฉลี่ยรายปี (°C)", (40, 665, 430, 280)),
        ("humidity-trend", "Average Humidity (%)", "ความชื้นเฉลี่ยรายปี (%)", (505, 665, 430, 280)),
        ("wind-trend", "Average Daily Max Wind (km/h)", "ลมสูงสุดรายวัน · ค่าเฉลี่ยรายปี (กม./ชม.)", (970, 665, 430, 280)),
    ]
    for key, measure, label, position in charts:
        clone("e4bdfbc86070ecc30b70", key, position, label, measure)
    add_text("footnote", "แหล่งข้อมูล: Open-Meteo ERA5 · จุดตัวแทนหนึ่งจุดต่อจังหวัด · ปี 2026 ไม่เต็มปี; การเทียบช่วงเวลาเท่ากันอยู่ในเว็บวิเคราะห์", (42, 1010, 1350, 40),
             "10pt", "#6E8594")
    print(PAGES / TOPIC)


if __name__ == "__main__":
    main()
