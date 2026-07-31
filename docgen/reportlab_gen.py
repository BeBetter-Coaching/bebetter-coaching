#!/usr/bin/env python3
"""BeBetter document-generator — ReportLab (strak, print-kwaliteit).

Geïnspireerd op het lactaat-rapport: navy/blauw palet, eyebrow met
letterspatiëring, genummerde sectiekoppen met lijntje, callout-kaders,
volle kleurbanden en Open Sans. ReportLab geeft nette tekstflow en
uitgelijnde beelden (geen Story-eigenaardigheden meer) en installeert
schoon op Streamlit Cloud.
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, Image, Flowable,
                                PageBreak, NextPageTemplate, KeepTogether)

from house_style import scrub_ai

HERE = os.path.dirname(os.path.abspath(__file__))


def _P(text, style):
    """Paragraph met de streepjes-vangrail erin: geen enkele '—' haalt de PDF."""
    return Paragraph(scrub_ai(text), style)
IMG = os.path.join(HERE, "img")
FONTS = os.path.join(HERE, "fonts")

# ── Merk (uit het lactaat-rapport geprikt) ──────────────────────────────────
NAVY   = HexColor("#0C1E34")
BLUE   = HexColor("#2E86C1")   # accent
BLUELB = HexColor("#1F6AA5")   # label-blauw (iets donkerder)
PANEL  = HexColor("#EAF2FB")   # licht paneel / callout-bg
PANELB = HexColor("#D6E8F7")   # iets sterker paneel
INK    = HexColor("#1c2733")
GREY   = HexColor("#5b6472")
LINE   = HexColor("#dbe2ec")
ZEBRA  = HexColor("#f3f7fc")
TIPBG  = HexColor("#FBF3E9")
TIPBAR = HexColor("#E8A24A")

PAGE_W, PAGE_H = A4
LMAR = RMAR = 20 * mm
TMAR = 26 * mm
BMAR = 20 * mm

# ── Fonts ───────────────────────────────────────────────────────────────────
def _reg():
    pdfmetrics.registerFont(TTFont("OS",   os.path.join(FONTS, "OpenSans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("OS-B", os.path.join(FONTS, "OpenSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("OS-I", os.path.join(FONTS, "OpenSans-Italic.ttf")))
    pdfmetrics.registerFont(TTFont("OS-SB", os.path.join(FONTS, "OpenSans-SemiBold.ttf")))
    pdfmetrics.registerFont(TTFont("OS-L", os.path.join(FONTS, "OpenSans-Light.ttf")))
    pdfmetrics.registerFontFamily("OS", normal="OS", bold="OS-B", italic="OS-I")


# ── Styles ──────────────────────────────────────────────────────────────────
def _styles():
    return {
        "body": ParagraphStyle("body", fontName="OS", fontSize=10.5, leading=16,
                               textColor=INK, spaceAfter=7),
        "why": ParagraphStyle("why", fontName="OS", fontSize=10.5, leading=15.5,
                              textColor=INK),
        "tip": ParagraphStyle("tip", fontName="OS", fontSize=9.8, leading=14.5,
                              textColor=INK),
        "stepnum": ParagraphStyle("stepnum", fontName="OS-B", fontSize=11,
                                  textColor=BLUE, leading=16),
        "step": ParagraphStyle("step", fontName="OS", fontSize=10.5, leading=15.5,
                               textColor=INK),
        "sec": ParagraphStyle("sec", fontName="OS-B", fontSize=14, textColor=NAVY,
                              leading=17),
        "secnum": ParagraphStyle("secnum", fontName="OS-B", fontSize=12,
                                 textColor=white, leading=20, alignment=TA_CENTER),
        "phcap": ParagraphStyle("phcap", fontName="OS", fontSize=8.5, textColor=GREY,
                                leading=11, alignment=TA_CENTER),
        "kl": ParagraphStyle("kl", fontName="OS", fontSize=10.5, leading=15, textColor=INK),
        "chk": ParagraphStyle("chk", fontName="OS", fontSize=10.5, leading=17, textColor=INK),
        "th": ParagraphStyle("th", fontName="OS-SB", fontSize=9.5, textColor=white, leading=13),
        "td": ParagraphStyle("td", fontName="OS", fontSize=10, textColor=INK, leading=13.5),
        "bron": ParagraphStyle("bron", fontName="OS", fontSize=8.6, textColor=GREY, leading=12.5),
        "oef_naam": ParagraphStyle("oef_naam", fontName="OS-B", fontSize=12.5, textColor=NAVY, leading=15),
        "oef_sets": ParagraphStyle("oef_sets", fontName="OS-B", fontSize=11, textColor=BLUE,
                                   leading=15, alignment=TA_RIGHT),
    }


# ── Custom flowables ────────────────────────────────────────────────────────
class SectionHeader(Flowable):
    """Genummerde sectiekop: blauw vierkantje met nr + titel + lijntje eronder."""
    def __init__(self, num, title, width, st):
        super().__init__()
        self.num, self.title, self.width, self.st = num, title, width, st
        self.height = 26

    def wrap(self, aw, ah):
        return self.width, self.height + 8

    def draw(self):
        c = self.canv
        s = 20
        c.setFillColor(NAVY)
        c.roundRect(0, 2, s, s, 3, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("OS-B", 11)
        c.drawCentredString(s/2, 7.5, str(self.num))
        c.setFillColor(NAVY)
        c.setFont("OS-B", 14)
        c.drawString(s + 10, 7.5, self.title)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.8)
        c.line(0, -6, self.width, -6)


def callout(text, st, bg, bar, style_key="why"):
    p = _P(text, st[style_key])
    t = Table([[p]], colWidths=[PAGE_W - LMAR - RMAR])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 3, bar),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


def placeholder(caption, st, w=120, h=150, label="SCREENSHOT"):
    cap = Paragraph(f'<font size="7" color="#9aa7b8">{label}</font><br/><br/>' + caption,
                    st["phcap"])
    t = Table([[cap]], colWidths=[w], rowHeights=[h])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#f4f6fa")),
        ("BOX", (0, 0), (-1, -1), 1, HexColor("#c2ccdb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _scaled_img(path, w=120):
    ir = Image(path)
    ratio = ir.imageHeight / float(ir.imageWidth)
    ir.drawWidth = w
    ir.drawHeight = w * ratio
    return ir


def steps_block(items, st, content_w, img_w=118, gutter=12):
    """Stappen als doorlopende genummerde lijst links; bijbehorende
    screenshots gestapeld in een smalle kolom rechts. Zo blijft er geen
    lege ruimte naast een enkele stap-regel staan en worden secties compact."""
    imgs = [im for (_t, im) in items if im]

    # veiligheidsrem: een gestapelde screenshot-kolom mag nooit hoger worden
    # dan een pagina, anders ontstaat een niet-splitsbare reuzenrij / lege pagina
    def _nat_h(im, w):
        if im.startswith("PH:"):
            return 150.0
        ir = Image(os.path.join(IMG, im))
        return w * ir.imageHeight / float(ir.imageWidth)
    if imgs:
        cap = (PAGE_H - TMAR - BMAR) - 120
        total = sum(_nat_h(im, img_w) for im in imgs) + 12 * (len(imgs) - 1)
        if total > cap:
            img_w *= cap / total

    left_w = content_w - (img_w + gutter if imgs else 0)

    rows = [[Paragraph(f"{i}.", st["stepnum"]), _P(txt, st["step"])]
            for i, (txt, _im) in enumerate(items, 1)]
    left = Table(rows, colWidths=[22, left_w - 22])
    left.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    if not imgs:
        return left

    irows = [[(placeholder(im[3:], st, w=img_w, h=150) if im.startswith("PH:")
               else _scaled_img(os.path.join(IMG, im), w=img_w))] for im in imgs]
    right = Table(irows, colWidths=[img_w])
    rstyle = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (0, 0), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    if len(irows) > 1:
        rstyle.append(("TOPPADDING", (0, 1), (-1, -1), 12))  # ruimte tussen beelden
    right.setStyle(TableStyle(rstyle))

    outer = Table([[left, right]], colWidths=[left_w, img_w + gutter])
    outer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    return outer


def _swatch(hexc, size=11, border=None):
    sw = Table([[""]], colWidths=[size], rowHeights=[size])
    style = [("BACKGROUND", (0, 0), (-1, -1), HexColor(hexc)) ] if hexc else []
    if border:
        style.append(("BOX", (0, 0), (-1, -1), 1, border))
    style.append(("ROUNDEDCORNERS", [2, 2, 2, 2]))
    sw.setStyle(TableStyle(style))
    return sw


def kleuren_table(items, st, content_w):
    rows = []
    for hexc, lbl, desc in items:
        txt = _P(f"<b>{lbl}:</b>&nbsp; {desc}", st["kl"])
        rows.append([_swatch(hexc), txt])
    t = Table(rows, colWidths=[22, content_w - 22])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def data_table(head, rows, st, content_w):
    """Nette tabel met navy kopregel en zebra-rijen (zoals het lactaat-rapport)."""
    ncols = len(head)
    cw = [content_w / ncols] * ncols
    data = [[_P(f"<b>{h}</b>", st["th"]) for h in head]]
    for r in rows:
        data.append([_P(c, st["td"]) for c in r])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE),
        ("ROUNDEDCORNERS", [4, 4, 0, 0]),
    ]
    for i in range(2, len(data), 2):
        style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    t = Table(data, colWidths=cw)
    t.setStyle(TableStyle(style))
    return t


def _oef_beeld(path, w, caption, st):
    """Eén beeldkolom van een oefeningkaart: afbeelding (of plekhouder) + bijschrift."""
    if path and not path.startswith("PH:"):
        img = _scaled_img(os.path.join(IMG, path), w=w)
    else:
        cap = path[3:] if path and path.startswith("PH:") else ""
        img = placeholder(cap, st, w=w, h=w, label="AFBEELDING")
    capp = Paragraph(f'<font color="#5b6472">{caption}</font>', st["phcap"])
    t = Table([[img], [capp]], colWidths=[w])
    t.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (0, 0), 0), ("TOPPADDING", (0, 1), (0, 1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def oefening_card(blk, st, content_w):
    """Kaart voor één oefening: naam + sets/reps, begin- en eindbeeld, techniek-cue."""
    pad = 14
    inner_w = content_w - 2 * pad
    img_w = min((inner_w - 16) / 2, 165)

    naam = Paragraph(f"<b>{blk['naam']}</b>", st["oef_naam"])
    sets = Paragraph(f"<b>{blk.get('sets', '')}</b>", st["oef_sets"])
    hdr = Table([[naam, sets]], colWidths=[inner_w - 110, 110])
    hdr.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    beelden = Table([[_oef_beeld(blk.get("begin"), img_w, "Begin", st),
                      _oef_beeld(blk.get("eind"), img_w, "Eind", st)]],
                    colWidths=[inner_w / 2, inner_w / 2])
    beelden.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    cue = _P(blk.get("cue", ""), st["step"])
    card = Table([[[hdr, Spacer(1, 9), beelden, Spacer(1, 9), cue]]], colWidths=[content_w])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F6F9FD")),
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("LEFTPADDING", (0, 0), (-1, -1), pad), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
    ]))
    return card


def bronnen_block(items, st, content_w):
    """Compacte, grijze genummerde bronnenlijst onderaan een document."""
    rows = [[_P(f"{i}.", st["bron"]), _P(x, st["bron"])] for i, x in enumerate(items, 1)]
    t = Table(rows, colWidths=[16, content_w - 16])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return t


def checklist(items, st, content_w):
    rows = [[_swatch(None, size=12, border=BLUE), _P(x, st["chk"])] for x in items]
    t = Table(rows, colWidths=[26, content_w - 26])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


# ── Cover + chrome ──────────────────────────────────────────────────────────
DOC = None  # ingevuld in main


def _eyebrow(c, x, y, text, color, size=9):
    c.setFillColor(color)
    c.setFont("OS-SB", size)
    c.drawString(x, y, " ".join(text))  # spatie tussen letters = letter-spacing


def on_cover(c, doc):
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H*0.60, PAGE_W, PAGE_H*0.40, stroke=0, fill=1)
    c.setFillColor(PANELB)
    c.rect(0, PAGE_H*0.16, PAGE_W, PAGE_H*0.44, stroke=0, fill=1)
    c.setFillColor(NAVY)
    c.rect(0, 0, PAGE_W, PAGE_H*0.16, stroke=0, fill=1)

    x = LMAR
    # wit logo linksboven in de navy band — ons handelsmerk
    lw = 150
    c.drawImage(os.path.join(IMG, "logo_wit.png"), x, PAGE_H*0.885, width=lw,
                height=lw / 2.535, preserveAspectRatio=True, anchor='sw', mask='auto')

    # team-foto rechtsboven, ronde hoeken zodat 'ie opgaat in de navy band
    pw = 116
    ph = pw / 0.667
    px2 = PAGE_W - RMAR
    px1 = px2 - pw
    ptop = PAGE_H*0.935
    py1 = ptop - ph
    c.drawImage(os.path.join(IMG, "team_round.png"), px1, py1, width=pw, height=ph,
                preserveAspectRatio=True, anchor='sw', mask='auto')
    c.setStrokeColor(HexColor("#2b4a5c")); c.setLineWidth(0.8)  # subtiele hairline
    c.roundRect(px1, py1, pw, ph, 6, stroke=1, fill=0)

    # titel, links
    c.setFillColor(white)
    c.setFont("OS-B", 30)
    c.drawString(x, PAGE_H*0.775, DOC["titel_1"])
    c.setFillColor(BLUE)
    c.setFont("OS-B", 30)
    c.drawString(x, PAGE_H*0.730, DOC["titel_2"])
    c.setFillColor(HexColor("#c7d6e8"))
    c.setFont("OS", 12.5)
    c.drawString(x, PAGE_H*0.690, DOC["ondertitel"])
    c.setFillColor(white)
    c.setFont("OS-B", 14)
    c.drawString(x, PAGE_H*0.642, DOC.get("voor", "Voor onze atleten"))

    # IN HET KORT als gebalanceerd 2×2-raster, verticaal gecentreerd in het paneel
    _eyebrow(c, x, PAGE_H*0.500, "IN HET KORT", BLUELB, 9)
    col_x = [x, PAGE_W/2 + 6]
    row_y = [PAGE_H*0.430, PAGE_H*0.310]
    for i, (lbl, val) in enumerate(DOC["kort"]):
        cx = col_x[i % 2]
        ry = row_y[i // 2]
        c.setFillColor(BLUELB); c.setFont("OS-SB", 9)
        c.drawString(cx, ry, lbl.upper())
        c.setFillColor(INK); c.setFont("OS", 10.5)
        c.drawString(cx, ry - 15, val)
        c.setStrokeColor(HexColor("#c3d6ea")); c.setLineWidth(0.6)
        c.line(cx, ry - 26, cx + (PAGE_W/2 - LMAR - 12), ry - 26)

    # footer band
    c.setFillColor(HexColor("#9bb6d4")); c.setFont("OS-SB", 8.5)
    c.drawCentredString(PAGE_W/2, PAGE_H*0.075,
                        "   ".join(["BeBetter Coaching", "·", "Jip van Lent", "·",
                                    "Oss & Bernheze", "·", "bebetter-coaching.nl"]))


def on_content(c, doc):
    # kop
    c.setStrokeColor(LINE); c.setLineWidth(0.8)
    c.line(LMAR, PAGE_H - 18*mm, PAGE_W - RMAR, PAGE_H - 18*mm)
    c.setFillColor(GREY); c.setFont("OS", 8)
    c.drawString(LMAR, PAGE_H - 17*mm, DOC["kop_links"])
    c.setFillColor(BLUELB); c.setFont("OS-SB", 8)
    c.drawRightString(PAGE_W - RMAR, PAGE_H - 17*mm, "BeBetter Coaching")
    # voet
    c.setStrokeColor(LINE)
    c.line(LMAR, 14*mm, PAGE_W - RMAR, 14*mm)
    c.setFillColor(GREY); c.setFont("OS", 8)
    c.drawString(LMAR, 11*mm, "bebetter-coaching.nl")
    c.drawRightString(PAGE_W - RMAR, 11*mm, f"Pagina {c.getPageNumber()}")


def build(doc_data, out):
    global DOC
    DOC = doc_data
    _reg()
    st = _styles()
    content_w = PAGE_W - LMAR - RMAR

    doc = BaseDocTemplate(out, pagesize=A4, leftMargin=LMAR, rightMargin=RMAR,
                          topMargin=TMAR, bottomMargin=BMAR, title=doc_data["pdftitel"])
    cover_frame = Frame(0, 0, PAGE_W, PAGE_H, id="cover",
                        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    content_frame = Frame(LMAR, BMAR, content_w, PAGE_H - TMAR - BMAR, id="content",
                          leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=on_cover),
        PageTemplate(id="content", frames=[content_frame], onPage=on_content),
    ])

    def render_block(blk):
        t = blk["t"]
        out = []
        if t == "para":
            out.append(_P(blk["x"], st["body"]))
        elif t == "why":
            out.append(callout(blk["x"], st, PANEL, NAVY, "why"))
            out.append(Spacer(1, 9))
        elif t == "tip":
            out.append(callout("<b>Tip.</b> " + blk["x"], st, TIPBG, TIPBAR, "tip"))
            out.append(Spacer(1, 9))
        elif t == "spoed":
            out.append(callout(blk["x"], st, HexColor("#FBE9E7"), HexColor("#D9534F"), "why"))
            out.append(Spacer(1, 9))
        elif t == "steps":
            out.append(steps_block(blk["items"], st, content_w))
            out.append(Spacer(1, 6))
        elif t == "kleuren":
            out.append(kleuren_table(blk["items"], st, content_w))
            out.append(Spacer(1, 8))
        elif t == "check":
            out.append(checklist(blk["items"], st, content_w))
        elif t == "tabel":
            out.append(data_table(blk["head"], blk["rows"], st, content_w))
            out.append(Spacer(1, 8))
        elif t == "bronnen":
            out.append(bronnen_block(blk["items"], st, content_w))
        elif t == "oefening":
            out.append(KeepTogether(oefening_card(blk, st, content_w)))
            out.append(Spacer(1, 10))
        return out

    avail_h = PAGE_H - TMAR - BMAR

    def _height(flowables):
        h = 0
        for f in flowables:
            try:
                h += f.wrap(content_w, 100000)[1]
            except Exception:
                pass
        return h

    story = [NextPageTemplate("content"), PageBreak()]
    for si, sec in enumerate(doc_data["secties"], 1):
        header = [SectionHeader(si, sec["titel"], content_w, st), Spacer(1, 10)]
        block_flows = [render_block(b) for b in sec["blocks"]]
        flat = header + [f for bf in block_flows for f in bf] + [Spacer(1, 12)]
        if _height(flat) <= avail_h - 6:
            # past op één pagina: heel hoofdstuk bijeen (geen halve hoofdstukken)
            story.append(KeepTogether(flat))
        else:
            # te lang (bv. een workout met veel kaarten): kop bij het eerste blok
            # houden, daarna laten vloeien — elke kaart blijft zelf heel
            story.append(KeepTogether(header + (block_flows[0] if block_flows else [])))
            for bf in block_flows[1:]:
                story.extend(bf)
            story.append(Spacer(1, 12))
    doc.build(story)
    print("OK:", out)
