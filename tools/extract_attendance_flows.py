#!/usr/bin/env python3
"""Extract Table 4 attendance-area flows from the 2025-26 Annual Enrollment Report.

The report markdown is the text extraction of:
https://www.seattleschools.org/wp-content/uploads/2026/09/Annual-Enrollment-Report_2025.pdf

Usage:
  python3 tools/extract_attendance_flows.py path/to/report.md attendance_flows.json
"""

import csv
import json
import re
import sys
from pathlib import Path

SOURCE_URL = "https://www.seattleschools.org/wp-content/uploads/2026/09/Annual-Enrollment-Report_2025.pdf"
REPORT_TITLE = "2025-26 Annual Enrollment Report"
REPORTING_DATE = "2025-10-01"
RETRIEVED = "2026-10-16"

LEVEL_WORDS = re.compile(r"\b(elementary|middle|high|school|international)\b", re.I)


def squash(value, drop_level=True):
    text = value.lower().replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"\*+", "", text)
    text = text.replace("b.f.", "bf").replace("b. f.", "bf").replace("jr.", "jr")
    text = text.replace("prek-8", "k-8").replace("pre-k-8", "k-8").replace("pk-8", "k-8")
    text = text.replace("k–8", "k-8")
    if drop_level:
        text = LEVEL_WORDS.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_schools(profile_path):
    with profile_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_squash = {}
    collisions = {}
    for row in rows:
        key = squash(row["school_name"])
        if key in by_squash:
            collisions.setdefault(key, [by_squash[key]]).append(row["school_key"])
        else:
            by_squash[key] = row["school_key"]
    for key in collisions:
        by_squash.pop(key, None)
    return rows, by_squash


MANUAL = {
    "bf day": "dayes",
    "b f day": "dayes",
    "martin luther king": "kinges",
    "martin luther king jr": "kinges",
    "david t denny intl": "dennyms",
    "denny intl": "dennyms",
    "denny": "dennyms",
    "west seattle elem": "westseattlees",
    "west seattle es": "westseattlees",
    "west seattle elementary": "westseattlees",
    "west seattle hs": "westseattlehs",
    "west seattle high": "westseattlehs",
    "stem k-8": "borenstemk8",
    "louisa boren stem k-8": "borenstemk8",
    "t marshall": "marshalles",
    "thurgood marshall": "marshalles",
    "jane addams ms": "addamsms",
    "jane addams": "addamsms",
    "hamilton": "hamiltonms",
    "hamilton intl": "hamiltonms",
    "aki kurose": "kurosems",
    "robert eagle staff": "eaglestaffms",
    "mercer intl": "mercerms",
    "mercer": "mercerms",
    "chief sealth intl": "chiefsealthhs",
    "chief sealth": "chiefsealthhs",
    "cleveland stem": "clevelandhs",
    "center school": "centerhs",
    "the center school": "centerhs",
    "bridges": "bridges-transition",
    "interagency": "interagency",
    "seattle world school": "sws",
    "middle college": "middlecollegehs",
    "alan t sugiyama": "sugiyamahs",
    "south shore pk-8": "southshorek8",
    "south shore prek-8": "southshorek8",
    "south shore": "southshorek8",
    "broadview thomson k-8": "broadviewk8",
    "broadview thomson": "broadviewk8",
    "catharine blaine k-8": "blainek8",
    "catharine blaine": "blainek8",
    "hazel wolf k-8": "hazelwolfk8",
    "hazel wolf": "hazelwolfk8",
    "tops k-8": "topsk8",
    "tops": "topsk8",
    "orca k-8": "orcak8",
    "pathfinder k-8": "pathfinderk8",
    "salmon bay k-8": "salmonbayk8",
    "licton springs k-8": "lictonspringsk8",
    "cascade virtual option k-12": "virtualoptionk12",
    "cascade parent partnership": "cppp",
    "cascade parent partnership k-8": "cppp",
    "john stanford intl": "stanfordes",
    "mcdonald intl": "mcdonaldes",
    "beacon hill intl": "beaconhilles",
    "dearborn park intl": "dearbornes",
    "concord intl": "concordes",
    "green lake": "greenlakees",
    "john hay": "hayes",
    "john muir": "muires",
    "john rogers": "rogerses",
    "bailey gatzert": "gatzertes",
    "daniel bagley": "bagleyes",
    "james baldwin": "baldwines",
    "wing luke": "lukees",
    "rising star": "risingstares",
    "rainier view": "rainierviewes",
    "rainier beach": "rainierbeachhs",
    "nathan hale": "halehs",
    "west woodland": "westwoodlandes",
    "thornton creek": "thorntoncreekes",
    "queen anne": "queenannees",
    "cedar park": "cedarparkes",
    "sacajawea": "sacajaweaes",
    "meany": "meanyms",
    "washington": "washingtonms",
    "whitman": "whitmanms",
    "madison": "madisonms",
    "eckstein": "ecksteinms",
    "mcclure": "mcclurems",
    "ballard": "ballardhs",
    "franklin": "franklinhs",
    "garfield": "garfieldhs",
    "ingraham": "ingrahamhs",
    "lincoln": "lincolnhs",
    "roosevelt": "roosevelths",
    "nova": "novahs",
    "skills center": "skillscenter",
    "seattle skills center": "skillscenter",
}


MANUAL_SQUASHED = {squash(name): key for name, key in MANUAL.items()}


def match_school(name, level, by_squash):
    key = squash(name)
    if key == "west seattle":
        if level == "high":
            return "westseattlehs"
        if level == "elementary":
            return "westseattlees"
        return None
    if key in MANUAL_SQUASHED:
        return MANUAL_SQUASHED[key]
    if key in by_squash:
        return by_squash[key]
    return None


def clean_cell(value):
    return re.sub(r"\s+", " ", value.replace("**", "").replace("*", "")).strip()


def parse_count(value):
    text = clean_cell(value).replace(",", "")
    if not text or not re.fullmatch(r"\d+", text):
        return None
    return int(text)


def split_row(line):
    parts = [clean_cell(part) for part in line.strip().strip("|").split("|")]
    return parts


def parse_side(rows, name_index, count_index):
    flows = []
    total = None
    for row in rows:
        if max(name_index, count_index) >= len(row):
            continue
        name = row[name_index]
        count = parse_count(row[count_index]) if count_index < len(row) else None
        if name.lower() == "grand total":
            total = count
            continue
        if not name or name.lower() in {"attendance area", "school", "total"}:
            continue
        if count is None:
            continue
        flows.append({"name": name, "count": count})
    return flows, total


def header_subject(cell):
    cell = re.sub(r"^Cont\.\s*", "", cell or "", flags=re.I).strip()
    match = re.search(r"Where Students Attending (.+?) Live(?: \((.+)\))?$", cell, re.I)
    if match:
        return match.group(1).strip(" ."), match.group(2), "enrolled"
    match = re.search(r"Where (?:the )?Students Living in the (.+?) Attendance Area Attend School", cell, re.I)
    if match:
        return match.group(1).strip(" ."), None, "residents"
    return None, None, None


def is_separator(row):
    return bool(row) and all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in row)


def is_column_header(row):
    labels = {cell.lower() for cell in row if cell}
    return bool(labels & {"attendance area", "school", "total"})


def stitch_table(rows):
    separator = next((index for index, row in enumerate(rows) if is_separator(row)), None)
    if separator is None:
        return None
    header_rows = rows[:separator]
    body = rows[separator + 1 :]
    while body and not is_column_header(body[0]) and not any(parse_count(cell) is not None for cell in body[0]):
        header_rows.append(body.pop(0))
    width = max((len(row) for row in header_rows), default=0)
    header = []
    for index in range(width):
        parts = [row[index] for row in header_rows if index < len(row) and row[index]]
        header.append(re.sub(r"\s+", " ", " ".join(parts)).strip())
    return header, body


def parse_tables(markdown):
    lines = markdown.splitlines()
    table_id = None
    level = None
    tables = []
    block = []
    recent = []

    def flush_block():
        nonlocal block
        if not block:
            return
        rows = [split_row(line) for line in block if line.strip().startswith("|")]
        block = []
        stitched = stitch_table(rows)
        if not stitched:
            return
        header, body = stitched
        left_name, left_scope, left_kind = header_subject(header[0] if header else "")
        right_cell = header[2] if len(header) > 2 else ""
        right_name, right_scope, right_kind = header_subject(right_cell)
        if not left_kind:
            return
        left_flows, left_total = parse_side(body, 0, 1)
        right_flows, right_total = parse_side(body, 2, 3) if right_kind else ([], None)
        if left_kind == "enrolled" and right_kind == "enrolled" and squash(left_name) == squash(right_name or ""):
            combined_total = left_total if left_total is not None else right_total
            if left_total is not None and right_total is not None and left_scope != right_scope:
                pass
            elif combined_total is not None and (left_total is None or right_total is None):
                left_flows = left_flows + right_flows
                left_total = combined_total
                right_kind = None
                right_flows, right_total = [], None
        tables.append({
            "table": table_id,
            "level": level,
            "printed_page": None,
            "left_name": left_name,
            "left_scope": left_scope,
            "left_kind": left_kind,
            "left_flows": left_flows,
            "left_total": left_total,
            "right_name": right_name,
            "right_scope": right_scope,
            "right_kind": right_kind,
            "right_flows": right_flows,
            "right_total": right_total,
        })
        recent.append(tables[-1])

    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"\d{1,3}", stripped):
            flush_block()
            for table in recent:
                table["printed_page"] = stripped
            recent.clear()
            continue
        if re.search(r"Table:\s*4-[ACE]", stripped, re.I):
            table_id = re.search(r"4-[ACE]", stripped, re.I).group(0).upper()
        if "Students in Elementary and K-8" in stripped:
            level = "elementary"
        elif "Students in Middle Schools by Attendance Area" in stripped:
            level = "middle"
        elif "Students in High Schools by Attendance Area" in stripped:
            level = "high"
        if stripped.startswith("|"):
            block.append(line)
        else:
            flush_block()
    flush_block()
    return tables


def default_scope(table_id, header_scope):
    if header_scope:
        scope = header_scope.upper().replace("TO", "–").replace("-", "–")
        scope = scope.replace("K–5", "K–5").replace("6–8", "6–8").replace("9–12", "9–12")
        return header_scope.replace("-", "–")
    return {"4-A": "K–5", "4-C": "6–8", "4-E": "9–12"}.get(table_id)


def flows_ok(flows, total):
    if total is None or not flows:
        return False
    return sum(item["count"] for item in flows) == total


def build(markdown, profile_path):
    _, by_squash = load_schools(profile_path)
    records = {}
    problems = []
    for table in parse_tables(markdown):
        if table["table"] not in {"4-A", "4-C", "4-E"}:
            continue
        subject = table["left_name"]
        school_key = match_school(subject, table["level"], by_squash)
        if not school_key:
            problems.append(f"unmatched subject: {subject} ({table['level']}, {table['table']})")
            continue
        sides = []
        if table["left_kind"] == "enrolled":
            sides.append(("enrolled", table["left_scope"], table["left_flows"], table["left_total"]))
        if table["right_kind"] == "residents":
            sides.append(("residents", table["right_scope"] or table["left_scope"], table["right_flows"], table["right_total"]))
        elif table["right_kind"] == "enrolled":
            sides.append(("enrolled", table["right_scope"], table["right_flows"], table["right_total"]))

        # Pair enrolled + residents when they describe the same grade band.
        enrolled = [side for side in sides if side[0] == "enrolled"]
        residents = [side for side in sides if side[0] == "residents"]
        if len(enrolled) == 1 and len(residents) == 1 and (enrolled[0][1] or None) == (residents[0][1] or enrolled[0][1] or None):
            groups = [(enrolled[0], residents[0])]
        else:
            groups = [((side if side[0] == "enrolled" else None), (side if side[0] == "residents" else None)) for side in sides]

        for enrolled_side, resident_side in groups:
            if enrolled_side and not flows_ok(enrolled_side[2], enrolled_side[3]):
                problems.append(f"sum mismatch enrolled {subject} {table['table']} page {table['printed_page']}: {sum(i['count'] for i in enrolled_side[2])} vs {enrolled_side[3]}")
                continue
            if resident_side and not flows_ok(resident_side[2], resident_side[3]):
                problems.append(f"sum mismatch residents {subject} {table['table']} page {table['printed_page']}: {sum(i['count'] for i in resident_side[2])} vs {resident_side[3]}")
                continue
            scope = default_scope(table["table"], (enrolled_side or resident_side)[1])
            entry = {
                "table": table["table"],
                "grade_scope": scope,
                "printed_page": table["printed_page"],
                "subject_name": subject,
                "enrolled_from": enrolled_side[2] if enrolled_side else None,
                "enrolled_total": enrolled_side[3] if enrolled_side else None,
                "residents_attend": resident_side[2] if resident_side else None,
                "residents_total": resident_side[3] if resident_side else None,
            }
            records.setdefault(school_key, []).append(entry)
    payload = {
        "source_url": SOURCE_URL,
        "title": REPORT_TITLE,
        "reporting_date": REPORTING_DATE,
        "retrieved": RETRIEVED,
        "note": "October 1, 2025 headcount. Table 4-A is grades K–5, including K–8 schools at grades K–5. Table 4-C is grades 6–8. Table 4-E is grades 9–12. Option schools have residence flows only. Preschool is not included.",
        "schools": records,
    }
    return payload, problems


def main():
    markdown_path, output_path = sys.argv[1:]
    markdown = Path(markdown_path).read_text(encoding="utf-8")
    profile = Path(__file__).resolve().parents[1] / "school_profiles.csv"
    payload, problems = build(markdown, profile)
    Path(output_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    schools = payload["schools"]
    print(f"schools {len(schools)} records {sum(len(v) for v in schools.values())}")
    sac = schools.get("sacajaweaes")
    print("sac", json.dumps(sac, ensure_ascii=False)[:500] if sac else "MISSING")
    if problems:
        print("PROBLEMS", len(problems))
        for problem in problems:
            print(" -", problem)


if __name__ == "__main__":
    main()
