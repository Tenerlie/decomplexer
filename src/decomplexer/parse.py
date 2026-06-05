from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from . import signatures

_PARSER = "lxml"

_FIELD_LABELS = {
    "Sygnatura": "signature",
    "Rodzaj": "rodzaj",
    "Tytuł aktu": "title",
    "Akty zmieniane": "akty_zmieniane",
    "Akty zmieniające": "akty_zmieniajace",
    "Data uchwalenia": "data_uchwalenia",
    "Data wejścia w życie": "data_wejscia",
    "Data wygaśnięcia": "data_wygasniecia",
    "Podmiot projektujący": "podmiot",
    "Organ wydający": "organ",
    "Kategoria aktu": "kategoria",
    "Uwagi": "uwagi",
}

KIND_AMENDING = "zmieniajacy"
KIND_AMENDED = "zmieniany"
KIND_LOOSES_POWER = "looses_power"

_LOOSES_POWER_RE = re.compile(r"looses?\s+power|traci\s+moc", re.IGNORECASE)

def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, _PARSER)

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

def _file_param(href: str) -> str | None:
    qs = parse_qs(urlparse(href).query)
    vals = qs.get("file")
    return vals[0] if vals else None

def _show_param(href: str) -> str | None:
    qs = parse_qs(urlparse(href).query)
    vals = qs.get("show")
    return vals[0] if vals else None

def _split_ext(filename: str) -> tuple[str, str]:
    if "." in filename:
        stem, _, ext = filename.rpartition(".")
        return stem, ext
    return filename, ""

@dataclass(slots=True)
class Relation:
    to_sig: str
    kind: str
    raw: str = ""

@dataclass(slots=True)
class ResultRow:
    signature: str
    show: str
    status: str
    title: str
    data_uchwalenia: str
    data_wygasniecia: str
    relations: list[Relation] = field(default_factory=list)

@dataclass(slots=True)
class ResultsPage:
    rows: list[ResultRow]
    has_next: bool
    total: int | None
    page_from: int | None = None
    page_to: int | None = None

_PAGE_RE = re.compile(r"(\d+)\s*-\s*(\d+)\s*(?:of|z)\s*(\d+)", re.IGNORECASE)

def parse_results_page(html: str) -> ResultsPage:
    soup = _soup(html)

    total = page_from = page_to = None
    m = _PAGE_RE.search(soup.get_text(" "))
    if m:
        page_from, page_to, total = int(m[1]), int(m[2]), int(m[3])

    nxt = soup.find("input", attrs={"name": "next"})
    has_next = nxt is not None and not nxt.has_attr("disabled")

    rows: list[ResultRow] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        if not cells:
            cells = tr.find_all("td")
        if not cells or not any(
            c.get("class") and c["class"][0] in ("st1", "st2") for c in cells
        ):
            continue

        open_link = tr.find("a", href=re.compile(r"show=", re.IGNORECASE))
        if open_link is None:
            continue
        href = open_link["href"]
        show = _show_param(href) or ""
        try:
            sig = signatures.canonical(show or cells[1].get_text())
        except signatures.SignatureError:
            continue
        status = (parse_qs(urlparse(href).query).get("status") or [""])[0]

        texts = [_clean(c.get_text()) for c in cells]
        title = texts[2] if len(texts) > 2 else ""
        data_uchwalenia = texts[3] if len(texts) > 3 else ""
        data_wygasniecia = texts[4] if len(texts) > 4 and texts[4] else ""

        relations: list[Relation] = []
        amending_text = texts[5] if len(texts) > 5 else ""
        amended_text = texts[6] if len(texts) > 6 else ""
        relations += _relations_from_text(amending_text, KIND_AMENDING)
        relations += _relations_from_text(amended_text, KIND_AMENDED)

        rows.append(
            ResultRow(
                signature=sig,
                show=show,
                status=status,
                title=title,
                data_uchwalenia=data_uchwalenia,
                data_wygasniecia=data_wygasniecia,
                relations=relations,
            )
        )

    return ResultsPage(rows=rows, has_next=has_next, total=total,
                       page_from=page_from, page_to=page_to)

def _relations_from_text(text: str, default_kind: str) -> list[Relation]:
    text = _clean(text)
    if not text or text == "\xa0":
        return []
    kind = KIND_LOOSES_POWER if _LOOSES_POWER_RE.search(text) else default_kind
    return [Relation(to_sig=sig, kind=kind, raw=text) for sig in signatures.find_all(text)]

def parse_act_frameset(html: str) -> str | None:
    soup = _soup(html)
    for frame in soup.find_all(["frame", "iframe"]):
        src = frame.get("src", "")
        if "todo=pokazMetryke" in src:
            return src
    return None

@dataclass(slots=True)
class DownloadFile:
    url: str
    filename: str
    ext: str

@dataclass(slots=True)
class Attachment:
    idx: int
    filename: str
    display_name: str
    description: str
    url: str
    ext: str

@dataclass(slots=True)
class Metrics:
    signature: str | None
    fields: dict[str, str]
    content_file: DownloadFile | None
    attachments: list[Attachment]
    relations: list[Relation]

def parse_metrics(html: str) -> Metrics:
    soup = _soup(html)

    fields: dict[str, str] = {}
    relations: list[Relation] = []
    for label_td in soup.find_all("td", class_="HED"):
        if not label_td.get("bgcolor"):
            continue
        label = _clean(label_td.get_text()).rstrip(":")
        key = _FIELD_LABELS.get(label)
        value_td = label_td.find_next_sibling("td")
        if value_td is None:
            continue
        value = _clean(value_td.get_text())
        if key:
            fields[key] = value
        if label == "Akty zmieniające":
            relations += _relations_from_metrics_cell(value_td, KIND_AMENDING)
        elif label == "Akty zmieniane":
            relations += _relations_from_metrics_cell(value_td, KIND_AMENDED)

    signature = None
    if fields.get("signature"):
        try:
            signature = signatures.canonical(fields["signature"])
        except signatures.SignatureError:
            signature = None

    content_file: DownloadFile | None = None
    attachments: list[Attachment] = []
    section = None

    for tr in soup.find_all("tr"):
        header = tr.find("td", class_="H")
        if header is not None:
            htext = _clean(header.get_text())
            if "Dokument" in htext:
                section = "content"
            elif "Załącznik" in htext or "Zalacznik" in htext:
                section = "attachments"
            else:
                section = None
            continue
        if section is None:
            continue

        dl = _download_anchor(tr)
        if dl is None:
            continue
        filename = _file_param(dl["href"])
        if not filename:
            continue
        stem, ext = _split_ext(filename)
        if not ext:
            continue

        if section == "content" and content_file is None:
            content_file = DownloadFile(url=dl["href"], filename=filename, ext=ext)
        elif section == "attachments":
            desc_td = tr.find("td", class_="HED")
            description = _clean(desc_td.get_text()) if desc_td else ""
            display_name = _attachment_display_name(tr)
            attachments.append(
                Attachment(
                    idx=len(attachments) + 1,
                    filename=filename,
                    display_name=display_name or stem,
                    description=description,
                    url=dl["href"],
                    ext=ext,
                )
            )

    return Metrics(
        signature=signature,
        fields=fields,
        content_file=content_file,
        attachments=attachments,
        relations=relations,
    )

def _download_anchor(tr) -> "object | None":
    for a in tr.find_all("a", href=re.compile(r"file=", re.IGNORECASE)):
        filename = _file_param(a["href"])
        if filename and "." in filename:
            return a
    return None

def _attachment_display_name(tr) -> str:
    for td in tr.find_all("td"):
        classes = td.get("class") or []
        if "HED" in classes:
            continue
        text = _clean(td.get_text())
        if text:
            return text
    return ""

def _relations_from_metrics_cell(td, kind: str) -> list[Relation]:
    rels: list[Relation] = []
    anchors = td.find_all("a", href=re.compile(r"show=", re.IGNORECASE))
    raw = _clean(td.get_text())
    if anchors:
        for a in anchors:
            target = _show_param(a["href"]) or a.get_text()
            try:
                rels.append(Relation(to_sig=signatures.canonical(target), kind=kind, raw=raw))
            except signatures.SignatureError:
                continue
    else:
        rels += _relations_from_text(raw, kind)
    return rels
