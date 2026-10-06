import sys
sys.path.insert(0, "C:/Users/Administrator/WorkBuddy/扑克/PokerSense/src")
sys.path.insert(0, "C:/Users/Administrator/WorkBuddy/扑克/PokerSense/tools")
from pathlib import Path
from tools.capture_card_calibration.dataset import RoiMeasurement, write_roi_measurements_csv
import csv as _csv

root = Path(r"C:/Users/Administrator/WorkBuddy/扑克/capture_card_calibration_20260903")
csv = root/"labels"/"roi_measurements.csv"
existing = []
with open(csv, newline="", encoding="utf-8") as f:
    for row in _csv.DictReader(f):
        existing.append(RoiMeasurement.from_row(row))

# 人工确认的空座 + 号深绿圆 ROI (放大图读数)
T30 = "session_002__f_000819"
T60 = "session_002__f_001806"
M = lambda f,x0,y0,x1,y1,s,src,note: RoiMeasurement(field=f,x0=x0,y0=y0,x1=x1,y1=y1,slot_id=s,source_frame=src,notes=note)
new_empty = [
    M("empty_slot",18,428,78,475,2,T30,"LM empty plus"),
    M("empty_slot",18,240,78,290,3,T30,"UL empty plus"),
    M("empty_slot",215,148,278,212,4,T30,"Top empty plus"),
    M("empty_slot",415,240,478,300,5,T30,"UR empty plus"),
    M("empty_slot",408,415,478,486,6,T60,"RM empty plus"),
    M("empty_slot",418,613,472,662,7,T30,"LR empty plus"),
]

all_meas = existing + new_empty
n = write_roi_measurements_csv(csv, all_meas)
# 统计
from collections import defaultdict
by = defaultdict(set)
for m in all_meas:
    by[m.field].add(m.slot_id)
print(f"total {n} measurements")
print("empty_slot slots:", sorted(by["empty_slot"]), "(need 1-7)")
print("dealer_search slots:", sorted(by["dealer_search"]), "(need 0-7)")
for m in all_meas:
    if m.x1>498 or m.y1>1080:
        print(f"  OUTSIDE {m.field} slot={m.slot_id}")
