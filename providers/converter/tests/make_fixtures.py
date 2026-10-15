#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["python-docx==1.2.0", "python-pptx==1.0.2", "reportlab==4.4.4", "openpyxl==3.1.5"]
# ///
"""Writes the "review" fixtures of the converter's tests: the same fictional content (a quarterly review of an invented
company, with a title, two headings, a paragraph with bold text, a bulleted list, a numbered list and a table of three columns)
as a Word document, a presentation, a PDF, a spreadsheet and an HTML page. The fixtures are committed; this script is how they
were made and is run only to remake them (it is not part of the tests, and nothing in the repository imports it):

  uv run providers/converter/tests/make_fixtures.py

Every name is fictional (Harbor Cafe Group is not a real company; example.invalid is a reserved domain).
"""
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures")

TITLE = "Harbor Cafe Quarterly Review"
INTRO = "The group opened two new cafés this quarter and the **loyalty programme** grew faster than planned."
WINS = ["Opening day sales beat the forecast", "Staff turnover fell to 8 percent", "Supplier costs stayed flat"]
STEPS = ["Hire a regional trainer", "Open the third cafe in spring", "Review the loyalty rewards"]
HEADER = ["Site", "Revenue", "Visits"]
ROWS = [["Dock Street", "48200", "9100"], ["Mill Lane", "39750", "7400"]]


def docx():
    import docx
    doc = docx.Document()
    doc.add_heading(TITLE, 1)
    p = doc.add_paragraph("The group opened two new cafés this quarter and the ")
    p.add_run("loyalty programme").bold = True
    p.add_run(" grew faster than planned.")
    doc.add_heading("Highlights", 2)
    for item in WINS:
        doc.add_paragraph(item, style="List Bullet")
    doc.add_heading("Next steps", 2)
    for item in STEPS:
        doc.add_paragraph(item, style="List Number")
    doc.add_heading("Sites", 2)
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    for cell, text in zip(table.rows[0].cells, HEADER):
        cell.text = text
    for row in ROWS:
        for cell, text in zip(table.add_row().cells, row):
            cell.text = text
    doc.save(os.path.join(OUT, "review.docx"))


def rich_docx():
    import docx
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    doc = docx.Document()
    doc.add_heading("Supplier handbook", 1)
    p = doc.add_paragraph("Orders go to ")
    p.add_run("Quay Beans Ltd").italic = True
    p.add_run(" before noon.")
    hidden = doc.add_paragraph().add_run("hidden docx text")
    hidden._r.get_or_add_rPr().append(OxmlElement("w:vanish"))
    doc.add_heading("Delivery rules", 2)
    doc.add_paragraph("Use the side door", style="List Bullet")
    doc.add_paragraph("Ring twice after nine", style="List Bullet 2")
    doc.add_paragraph("Sign the delivery note", style="List Bullet")
    table = doc.add_table(rows=3, cols=2)
    table.style = "Table Grid"
    for row, (a, b) in zip(table.rows, [("Item", "Unit"), ("Beans", "kilo"), ("Milk", "litre")]):
        row.cells[0].text, row.cells[1].text = a, b
    doc.save(os.path.join(OUT, "rich.docx"))


def columns_pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, FrameBreak
    styles = getSampleStyleSheet()
    width, height = letter
    half = (width - 144) / 2
    frames = [Frame(72, 72, half, height - 144, id="left"), Frame(72 + half + 0, 72, half, height - 144, id="right")]
    doc = BaseDocTemplate(os.path.join(OUT, "columns.pdf"), pagesize=letter, title="Two columns", invariant=True)
    doc.addPageTemplates([PageTemplate(id="two", frames=frames)])
    left = ("The left column opens the guide for new staff. It explains how the morning shift begins, who unlocks the doors, "
            "and where the cash float is counted before the first customer arrives. Every step has an owner.")
    right = ("The right column covers closing time. It lists the cleaning tasks, the order of the checks, and how the day's "
             "takings are sealed and signed by two people before the safe is locked.")
    later = ("A second page repeats the contacts: the manager on duty, the supplier hotline and the maintenance desk, "
             "each with an extension number that is printed on the back of the staff card.")
    flow = [Paragraph("Opening and closing guide", styles["Heading1"]), Paragraph(left, styles["BodyText"]), FrameBreak(),
            Paragraph(right, styles["BodyText"]), FrameBreak(), Paragraph(later, styles["BodyText"])]
    doc.build(flow)


def rich_html():
    page = ("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><title>Kitchen guide</title>"
            "<style>.x{color:blue}</style></head><body>\n"
            "<h1>Kitchen guide</h1>\n<p>Rinse the beans &amp; dry them. Use <code>mode=fast</code> only for small batches.</p>\n"
            "<ul><li>Prepare<ul><li>Wash</li><li>Dry</li></ul></li><li>Roast</li></ul>\n"
            "<blockquote>Taste before you serve.</blockquote>\n"
            "<pre>step 1\nstep 2</pre>\n"
            "<p><img src=\"beans.png\" alt=\"a bowl of beans\"> <a href=\"https://cafe.example/guide\">full guide</a></p>\n"
            "<!-- comment text that is not content -->\n"
            "<noscript>noscript text</noscript><template><p>template text</p></template>\n"
            "<script>var x = 'hidden script text';</script>\n"
            "</body></html>\n")
    with open(os.path.join(OUT, "rich.html"), "w", encoding="utf-8") as f:
        f.write(page)


def pptx():
    import pptx
    from pptx.util import Inches
    deck = pptx.Presentation()
    first = deck.slides.add_slide(deck.slide_layouts[0])
    first.shapes.title.text = TITLE
    first.placeholders[1].text = "Fictional deck for the converter's tests"
    second = deck.slides.add_slide(deck.slide_layouts[1])
    second.shapes.title.text = "Highlights"
    frame = second.placeholders[1].text_frame
    frame.text = WINS[0]
    for item in WINS[1:]:
        frame.add_paragraph().text = item
    second.notes_slide.notes_text_frame.text = "Speaker note: thank the Dock Street team."
    third = deck.slides.add_slide(deck.slide_layouts[5])
    third.shapes.title.text = "Sites"
    shape = third.shapes.add_table(3, 3, Inches(0.5), Inches(1.8), Inches(8), Inches(1.5))
    for r, row in enumerate([HEADER] + ROWS):
        for c, text in enumerate(row):
            shape.table.cell(r, c).text = text
    deck.save(os.path.join(OUT, "review.pptx"))


def pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle
    styles = getSampleStyleSheet()
    flow = [Paragraph(TITLE, styles["Heading1"]),
            Paragraph("The group opened two new cafés this quarter and the <b>loyalty programme</b> grew faster than planned.",
                      styles["BodyText"]),
            Paragraph("Highlights", styles["Heading2"]),
            ListFlowable([ListItem(Paragraph(t, styles["BodyText"])) for t in WINS], bulletType="bullet"),
            Paragraph("Next steps", styles["Heading2"]),
            ListFlowable([ListItem(Paragraph(t, styles["BodyText"])) for t in STEPS], bulletType="1"),
            PageBreak(),
            Paragraph("Sites", styles["Heading2"])]
    table = Table([HEADER] + ROWS)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black"), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]))
    flow.append(table)
    SimpleDocTemplate(os.path.join(OUT, "review.pdf"), pagesize=letter, title=TITLE, invariant=True).build(flow)


def xlsx():
    import openpyxl
    book = openpyxl.Workbook()
    sites = book.active
    sites.title = "Sites"
    sites.append(HEADER)
    for row in ROWS:
        sites.append([row[0], int(row[1]), int(row[2])])
    sites.append(["Total", 87950, 16500])
    notes = book.create_sheet("Notes")
    notes.append(["Highlights"])
    for item in WINS:
        notes.append([item])
    book.save(os.path.join(OUT, "review.xlsx"))


def html():
    items = "".join(f"<li>{t}</li>" for t in WINS)
    steps = "".join(f"<li>{t}</li>" for t in STEPS)
    body = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td></tr>" for a, b, c in ROWS)
    head = "".join(f"<th>{h}</th>" for h in HEADER)
    page = (f"<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><title>{TITLE}</title>"
            "<style>p{color:red}</style></head><body>\n"
            f"<h1>{TITLE}</h1>\n<p>The group opened two new cafés this quarter and the <strong>loyalty programme</strong> grew "
            "faster than planned. See <a href=\"https://cafe.example/loyalty\">the loyalty page</a>.</p>\n"
            f"<h2>Highlights</h2>\n<ul>{items}</ul>\n<h2>Next steps</h2>\n<ol>{steps}</ol>\n<h2>Sites</h2>\n"
            f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>\n"
            "<script>alert('hidden script text')</script></body></html>\n")
    with open(os.path.join(OUT, "review.html"), "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for make in (docx, rich_docx, pptx, pdf, columns_pdf, xlsx, html, rich_html):
        make()
    print("wrote the review fixtures to", OUT)
