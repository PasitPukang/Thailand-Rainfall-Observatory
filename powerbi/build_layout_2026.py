"""Rearrange a Power BI Project (PBIP) report into a readable 2026 overview."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "Thailand_Rainfall_2018_2026.Report" / "definition"
PAGE = "7c266bc4c4c4cb19068e"
PAGE_DIR = REPORT / "pages" / PAGE
TITLE_ID = "e0fd050fcd83dcf0c326"
POSITIONS = {
    "fd314105e6033b0ab04c": (40, 160, 280, 150),
    "bd90e7e838e2580d0522": (335, 160, 280, 150),
    "f7f6c2ea257addc830eb": (630, 160, 280, 150),
    "01aa2b481b9696865277": (925, 160, 475, 150),
    "e4bdfbc86070ecc30b70": (40, 350, 660, 365),
    "3eaa146c948202c40b0c": (720, 350, 680, 365),
    TITLE_ID: (40, 22, 1100, 60),
}
THAI_TITLES = {
    "fd314105e6033b0ab04c": "วันฝนหนัก · รวมจุดที่เลือก",
    "bd90e7e838e2580d0522": "วันฝนหนักมาก · รวมจุดที่เลือก",
    "f7f6c2ea257addc830eb": "ฝนสะสม · รวมจุดที่เลือก",
    "01aa2b481b9696865277": "เลือกจังหวัดเพื่อดูรายละเอียด",
    "e4bdfbc86070ecc30b70": "ฝนสะสมรายปี | 2026 ยังไม่ครบปี",
    "3eaa146c948202c40b0c": "เปรียบเทียบวันฝนหนักรายจังหวัด",
}


def literal(value: str | bool) -> dict:
    if isinstance(value, bool):
        return {"expr": {"Literal": {"Value": str(value).lower()}}}
    return {"expr": {"Literal": {"Value": "'" + value.replace("'", "''") + "'"}}}


def textbox(name: str, content: str, x: int, y: int, width: int, height: int,
            size: str, color: str, bold: bool = False) -> dict:
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.13.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": 100 + y, "height": height, "width": width, "tabOrder": 20 + y},
        "visual": {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [{
                "value": content,
                "textStyle": {"fontFamily": "Segoe UI", "fontSize": size,
                              "fontWeight": "bold" if bold else "normal", "color": color},
            }], "horizontalTextAlignment": "left"}]}}]},
            "visualContainerObjects": {"background": [{"properties": {"show": literal(False)}}]},
            "drillFilterOtherVisuals": True,
        },
    }


def patch_visual(item: dict, visual_id: str) -> dict:
    if visual_id == TITLE_ID:
        return textbox(visual_id, "ภาพรวมฝนประเทศไทย", *POSITIONS[visual_id], "28pt", "#17324A", True)
    x, y, width, height = POSITIONS[visual_id]
    item["position"].update(x=x, y=y, width=width, height=height, tabOrder=y)
    visual = item["visual"]
    visual.setdefault("visualContainerObjects", {})["title"] = [{"properties": {
        "show": literal(True), "text": literal(THAI_TITLES[visual_id]),
        "fontColor": {"solid": {"color": literal("#17324A")}},
        "fontSize": {"expr": {"Literal": {"Value": "15D"}}},
        "bold": literal(True),
    }}]
    if visual_id == "01aa2b481b9696865277":
        visual.get("objects", {}).pop("general", None)  # Clear the saved Tak selection.
        visual.setdefault("objects", {}).setdefault("data", [{"properties": {}}])[0]["properties"]["mode"] = literal("Dropdown")
    return item


def main() -> None:
    if not PAGE_DIR.exists():
        raise FileNotFoundError(PAGE_DIR)
    page_path = PAGE_DIR / "page.json"
    page = json.loads(page_path.read_text(encoding="utf-8"))
    page.update(displayName="ภาพรวมฝนไทย", width=1440, height=810)
    page_path.write_text(json.dumps(page, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for path in (PAGE_DIR / "visuals").glob("*/visual.json"):
        item = json.loads(path.read_text(encoding="utf-8"))
        visual_id = item["name"]
        if visual_id in POSITIONS:
            path.write_text(json.dumps(patch_visual(item, visual_id), ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    extra = [
        ("subtitle", "ข้อมูล ERA5 ณ จุดตัวแทน 77 จังหวัด  •  ปี 2026 ยังไม่ครบทั้งปี", 42, 92, 1100, 33, "12pt", "#5F7789", False),
        ("footnote", "แหล่งข้อมูล: Open-Meteo ERA5  |  กด Refresh หลัง Airflow ส่งออก CSV ใหม่  |  พิกัดหนึ่งจุดไม่ใช่ค่าเฉลี่ยทั้งจังหวัด", 42, 757, 1340, 28, "10pt", "#6E8594", False),
    ]
    for key, content, x, y, width, height, size, color, bold in extra:
        visual_id = hashlib.sha1(f"thailand-rainfall-{key}".encode()).hexdigest()[:20]
        item = textbox(visual_id, content, x, y, width, height, size, color, bold)
        path = PAGE_DIR / "visuals" / visual_id / "visual.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(PAGE_DIR)


if __name__ == "__main__":
    main()
