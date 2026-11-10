"""Quotation PDF, made **only** from the frozen snapshot (docs/04 §13): it never reads live prices, so the
document always shows exactly what was approved. The same snapshot always gives the same bytes
(ReportLab's invariant mode), so a reissued PDF can be compared with the original."""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TAX_TEXT = {
    "inclusive": "Prices include tax.",
    "exclusive": "Prices exclude tax; tax is added at the applicable rate when invoiced.",
    "not_applicable": "No tax applies to these prices.",
}


def _esc(value: Any) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(snapshot: dict[str, Any], snapshot_hash: str, recipient: str | None = None) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Quotation {snapshot['quote_number']} revision {snapshot['revision_no']}",
        author="Mixt Academy",
        invariant=1,
    )
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    story: list[Any] = [
        Paragraph("Mixt Academy", styles["Title"]),
        Paragraph(
            f"Quotation {_esc(snapshot['quote_number'])} (revision {snapshot['revision_no']})", styles["Heading2"]
        ),
        Paragraph(
            f"Customer: {_esc(snapshot['customer']['name'])} ({_esc(snapshot['customer']['account_number'])})"
            + (f"<br/>For the attention of: {_esc(recipient)}" if recipient else ""),
            styles["Normal"],
        ),
        Paragraph(f"Valid until: {_esc(snapshot['valid_until'])}", styles["Normal"]),
        Spacer(1, 6 * mm),
    ]
    rows: list[list[Any]] = [["Package", "Quantity", "List price", "Promotion", "Discount", "Total"]]
    for line in snapshot["lines"]:
        unit = "classes" if line["unit_type"] == "class" else "hours"
        promotion = ""
        if line["promotion"]:
            promotion = line["promotion"]["name"]
            if line["bonus_units"]:
                promotion += f" (+{line['bonus_units']} {unit})"
            elif line["promotion_discount_minor"]:
                promotion += f" ({line.get('promotion_discount') or line['promotion_discount_minor']} off)"
        rows.append(
            [
                Paragraph(_esc(line["display_name"]), styles["Normal"]),
                f"{line['quantity']} {unit}",
                line["list_total"],
                Paragraph(_esc(promotion), styles["Normal"]),
                f"{line.get('discount') or line['discount_minor']} off" if line["discount_minor"] else "",
                line["final_total"],
            ]
        )
    totals = snapshot["totals"]
    rows.append(["", "", "", "", "Total", totals["total"]])
    table = Table(rows, colWidths=[44 * mm, 24 * mm, 28 * mm, 36 * mm, 18 * mm, 28 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (-2, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ]
        )
    )
    story += [table, Spacer(1, 4 * mm)]
    story.append(
        Paragraph(
            f"All amounts in {_esc(snapshot['currency'])}. {TAX_TEXT.get(snapshot['tax_treatment'], '')}",
            styles["Normal"],
        )
    )
    benefits = sorted({b for line in snapshot["lines"] for b in line["benefits"]})
    if benefits:
        story += [Spacer(1, 4 * mm), Paragraph("Included", styles["Heading3"])]
        story += [Paragraph(f"• {_esc(b)}", styles["Normal"]) for b in benefits]
    terms = [line["promotion"] for line in snapshot["lines"] if line["promotion"] and line["promotion"].get("terms")]
    if terms:
        story += [Spacer(1, 4 * mm), Paragraph("Promotion terms", styles["Heading3"])]
        story += [Paragraph(f"{_esc(t['name'])}: {_esc(t['terms'])}", styles["Normal"]) for t in terms]
    if snapshot.get("customer_note"):
        story += [Spacer(1, 4 * mm), Paragraph(_esc(snapshot["customer_note"]), styles["Normal"])]
    story += [
        Spacer(1, 8 * mm),
        Paragraph(
            f"Reference {_esc(snapshot['quote_number'])}-{snapshot['revision_no']} · {snapshot_hash[:16]}", small
        ),
    ]
    doc.build(story)
    return buffer.getvalue()
