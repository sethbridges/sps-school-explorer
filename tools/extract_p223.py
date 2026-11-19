#!/usr/bin/env python3
"""Extract a monthly SPS P223 "Enrollment Data by School and Grade" PDF.

The official index is:
https://www.seattleschools.org/departments/dots/data-reporting/enrollment-reporting-p223/

Each school is one table. September reports use a separate count date for grades
1–12 and for preschool/kindergarten; other months print one count date for both.
Landscape reports place one school on each page. The November 2026 report is
portrait and stacks two schools on each page; both schools share that physical
PDF page, and the printed footer is the first school's report page.

Blank grade rows inside a school table are confirmed zeros. Schools with no
table are not zeros. Reporting units that are not schools (experimental
education, non-public agencies, Open Doors, private special-education services)
are returned separately for district reconciliation.

Requires PyMuPDF (`import pymupdf`).

Usage:
  python3 tools/extract_p223.py /path/to/P223.pdf
"""

import json
import re
import sys
from pathlib import Path

GRADE_LABELS = ["Preschool", "K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
GRADE_FIELDS = ["regular", "bilingual", "special_ed", "male", "female", "nonbinary", "total", "p223_count", "p223_fte"]
MEASURES = ["regular", "bilingual", "special_ed", "male", "female", "nonbinary", "total", "p223_count", "p223_fte"]

# PDF names that are district reporting units, not profile schools.
# Canonical names match source_provenance.json p223_reconciliation.other_units.
OTHER_UNITS = {
    "experimental ed unit": "Exp Ed Unit",
    "exp ed unit": "Exp Ed Unit",
    "non public agencies": "Non-Public Agencies",
    "interagency open doors program": "Interagency Open Doors Program",
    "lcs open doors program": "LCS Open Doors Program",
    "special ed private svcs": "Special Ed Private Svcs",
}

LONG_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4}"
)
NUMBER = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$|^\.\d+$")


def norm_name(value):
    text = value.lower().replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_number(token):
    if not NUMBER.match(token):
        return None
    return float(token.replace(",", ""))


def iso_long(text):
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }
    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})", text.strip())
    if not match or match.group(1).lower() not in months:
        raise ValueError(f"Unrecognized count date: {text!r}")
    return f"{int(match.group(3)):04d}-{months[match.group(1).lower()]:02d}-{int(match.group(2)):02d}"


def format_count(value):
    if abs(value - round(value)) > 1e-6:
        raise ValueError(f"Non-integer count {value}")
    return str(int(round(value)))


def format_fte(value):
    rounded = round(value, 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    text = f"{rounded:.2f}".rstrip("0").rstrip(".")
    return text


def cluster_rows(words, tolerance=1.5):
    rows = []
    for word in sorted(words, key=lambda item: (item[1], item[0])):
        y = word[1]
        if rows and abs(y - rows[-1][0]) <= tolerance:
            rows[-1][1].append(word)
            rows[-1][0] = (rows[-1][0] * (len(rows[-1][1]) - 1) + y) / len(rows[-1][1])
        else:
            rows.append([y, [word]])
    return rows


def line_text(words):
    return " ".join(word[4] for word in sorted(words, key=lambda item: item[0]))


def parse_count_dates(text):
    pair = re.search(
        rf"({LONG_MONTH})\s*\(Grades\s*1-12\)\s*/\s*({LONG_MONTH})\s*\(PS/K\)",
        text,
    )
    if pair:
        return iso_long(pair.group(1)), iso_long(pair.group(2))
    single = re.search(rf"({LONG_MONTH})", text)
    if not single:
        raise ValueError(f"No count date in header: {text!r}")
    day = iso_long(single.group(1))
    return day, day


def parse_created(text):
    match = re.search(r"Report created on\s+(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not match:
        raise ValueError(f"No report-created date in: {text!r}")
    month, day, year = (int(match.group(i)) for i in (1, 2, 3))
    return f"{year:04d}-{month:02d}-{day:02d}"


def school_blocks(page):
    words = page.get_text("words")
    anchors = [word for word in words if word[4] == "School:"]
    anchors.sort(key=lambda word: word[1])
    if not anchors:
        return []
    blocks = []
    for index, anchor in enumerate(anchors):
        top = anchor[1] - 36
        if index:
            top = max(top, anchors[index - 1][1] + 20)
        bottom = anchors[index + 1][1] - 28 if index + 1 < len(anchors) else page.rect.height
        block_words = [word for word in words if top <= word[1] < bottom]
        blocks.append((anchor, block_words))
    footers = [
        word for word in words
        if word[4] == "Page" and word[1] > page.rect.height - 90
    ]
    printed = None
    if footers:
        footer = min(footers, key=lambda word: word[0])
        number = [word for word in words if abs(word[1] - footer[1]) <= 2 and word[0] > footer[0]]
        if not number or not number[0][4].isdigit():
            raise ValueError(f"Footer page label has no number on PDF page {page.number + 1}")
        printed = int(number[0][4])
    return [(anchor, block_words, printed, index) for index, (anchor, block_words) in enumerate(blocks)]


def parse_grade_row(label_word, row_words):
    numbers = []
    for word in sorted(row_words, key=lambda item: item[0]):
        if word[0] <= label_word[2] + 2:
            continue
        value = parse_number(word[4])
        if value is None:
            continue
        numbers.append(value)
    if not numbers:
        return {field: 0.0 for field in GRADE_FIELDS}
    if len(numbers) != len(GRADE_FIELDS):
        raise ValueError(
            f"Grade {label_word[4]} has {len(numbers)} numbers, expected {len(GRADE_FIELDS)}: {numbers}"
        )
    return dict(zip(GRADE_FIELDS, numbers))


def parse_block(anchor, block_words, pdf_page, printed_page):
    rows = cluster_rows(block_words)
    name_words = [
        word for word in block_words
        if abs(word[1] - anchor[1]) <= 2 and word[0] > anchor[0]
    ]
    name = line_text(name_words).strip()
    if not name:
        raise ValueError(f"Missing school name on PDF page {pdf_page}")
    header_lines = [line_text(words) for y, words in rows if y < anchor[1] - 4]
    date_line = next((line for line in header_lines if re.search(LONG_MONTH, line)), "")
    if not date_line:
        raise ValueError(f"Missing count date for {name} on PDF page {pdf_page}")
    grades_date, preschool_date = parse_count_dates(date_line)
    body = "\n".join(line_text(words) for _, words in rows)
    created = parse_created(body)

    label_rows = []
    for y, words in rows:
        labels = [
            word for word in words
            if anchor[1] + 8 < word[1] and 90 <= word[0] < 160
            and (word[4] in GRADE_LABELS or word[4] == "Total")
        ]
        if labels:
            label_rows.append((y, labels[0], words))
    found = [word[4] for _, word, _ in label_rows]
    expected = GRADE_LABELS + ["Total"]
    if found != expected:
        raise ValueError(f"{name} on PDF page {pdf_page} has grade labels {found}, expected {expected}")

    grades = {}
    for _, label, words in label_rows:
        key = "total" if label[4] == "Total" else label[4]
        grades[key] = parse_grade_row(label, words)
    total = grades.pop("total")
    for measure in MEASURES:
        parts = [grades[label][measure] for label in GRADE_LABELS]
        limit = 0.08 if measure == "p223_fte" else 0
        if abs(sum(parts) - total[measure]) > limit + 1e-6:
            raise ValueError(
                f"{name} grade {measure} sums to {sum(parts)} but the published total is {total[measure]}"
            )
    gender = total["male"] + total["female"] + total["nonbinary"]
    if abs(gender - total["total"]) > 1e-6:
        raise ValueError(f"{name} gender {gender} does not equal total {total['total']}")
    for label in GRADE_LABELS:
        row = grades[label]
        if abs(row["male"] + row["female"] + row["nonbinary"] - row["total"]) > 1e-6:
            raise ValueError(f"{name} grade {label} gender does not equal its total")

    footnote = ""
    notes = re.search(r"NOTES:(.*?)Report created", body, re.S)
    if notes:
        footnote = re.sub(r"\s+", " ", notes.group(1)).strip()
    return {
        "reporting_name": re.sub(r"\s+", " ", name).strip(),
        "pdf_page": pdf_page,
        "report_page": printed_page,
        "count_date_grades_1_12": grades_date,
        "count_date_preschool_k": preschool_date,
        "report_created_date": created,
        "grades": grades,
        "total": total,
        "footnote": footnote,
    }


def parse_pdf(path):
    import pymupdf

    document = pymupdf.open(path)
    schools = []
    for page in document:
        for anchor, block_words, printed, block_index in school_blocks(page):
            record = parse_block(anchor, block_words, page.number + 1, printed)
            record["block_index"] = block_index
            schools.append(record)
    if not schools:
        raise ValueError(f"No school tables in {path}")
    # One table per page: the footer is that table's report page.
    # Two tables per page: the footer is the sheet number, and the report
    # pages are the pair (2n-1, 2n). The sequence must stay contiguous.
    groups = []
    for record in schools:
        if record["block_index"] == 0 or not groups:
            groups.append([record])
        else:
            groups[-1].append(record)
    expected = 1
    for group in groups:
        printed = group[0]["report_page"]
        if printed is None:
            raise ValueError(f"No printed page footer for {group[0]['reporting_name']}")
        if len(group) == 1:
            pages = [printed]
        else:
            pages = [printed * len(group) - (len(group) - 1) + offset for offset in range(len(group))]
        if pages[0] != expected:
            raise ValueError(
                f"{group[0]['reporting_name']} report page {pages[0]} (footer {printed}, "
                f"{len(group)} tables on the sheet), expected {expected}"
            )
        for record, page in zip(group, pages):
            record["report_page"] = page
            expected += 1
    district = [record for record in schools if norm_name(record["reporting_name"]) == "district total"]
    if len(district) != 1:
        raise ValueError(f"Expected one District Total table, found {len(district)}")
    units = [record for record in schools if record not in district]
    return {
        "path": str(path),
        "page_count": document.page_count,
        "metadata_created": document.metadata.get("creationDate") or "",
        "units": units,
        "district": district[0],
        "footnotes": sorted({record["footnote"] for record in schools if record["footnote"]}),
    }


def classify(parsed, aliases):
    """Split parsed units into profile schools and excluded reporting units.

    aliases maps norm_name(reporting name) -> school_key. Unknown names fail.
    """
    matched = []
    other = []
    seen = {}
    for record in parsed["units"]:
        key = norm_name(record["reporting_name"])
        if key in OTHER_UNITS:
            record = dict(record)
            record["canonical_name"] = OTHER_UNITS[key]
            other.append(record)
            continue
        if key not in aliases:
            raise KeyError(f"Unmapped P223 reporting name: {record['reporting_name']!r}")
        school_key = aliases[key]
        if school_key in seen:
            raise ValueError(
                f"{record['reporting_name']!r} and {seen[school_key]!r} both map to {school_key}"
            )
        seen[school_key] = record["reporting_name"]
        record = dict(record)
        record["school_key"] = school_key
        matched.append(record)
    return matched, other


def reconciliation_record(month, school_year, matched, other, district):
    def measures(total):
        out = {}
        for key in ("regular", "bilingual", "special_ed", "male", "female", "nonbinary", "total", "p223_count", "p223_fte"):
            value = total[key]
            out[key] = int(round(value)) if key != "p223_fte" else round(value, 2)
        return out

    for measure in MEASURES:
        parts = [record["total"][measure] for record in matched + other]
        limit = 0.08 if measure == "p223_fte" else 0
        published = district["total"][measure]
        if abs(sum(parts) - published) > limit + 1e-6:
            raise ValueError(
                f"District {measure} is {published}; school and other units sum to {sum(parts)}"
            )
    return {
        "month": month,
        "school_year": school_year,
        "matched": len(matched),
        "reporting_units": len(matched) + len(other),
        "district_totals": measures(district["total"]),
        "other_units": [
            {"name": record["canonical_name"], **measures(record["total"])}
            for record in other
        ],
    }


def main(argv):
    if len(argv) != 2:
        print("Usage: python3 tools/extract_p223.py REPORT.pdf", file=sys.stderr)
        return 2
    parsed = parse_pdf(Path(argv[1]))
    summary = {
        "pages": parsed["page_count"],
        "tables": len(parsed["units"]) + 1,
        "names": [record["reporting_name"] for record in parsed["units"]],
        "district": parsed["district"]["total"],
        "created": parsed["district"]["report_created_date"],
        "count_dates": [
            parsed["district"]["count_date_grades_1_12"],
            parsed["district"]["count_date_preschool_k"],
        ],
        "footnotes": parsed["footnotes"],
    }
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
