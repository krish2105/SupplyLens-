"""Rule-based extraction of key contract terms, each with the character span it was read from (Phase 8 WP7).

Course week 8, "document processing with AI": the deterministic baseline. Regular expressions and a sentence splitter
read the plain text of one document version and return DRAFT fields. Nothing is stored and nothing reaches planning:
a person must confirm a field before it is used, and confirming is a later step (it needs a terms record of its own).

Fields (FIELDS): parties, agreement_date, effective_date, expiry_date (term and expiry), renewal,
termination_for_convenience, exclusivity, minimum_commitment, price, moq (minimum order quantity), lead_time.
Each result is ExtractedField(field, value, start, end, source="rule") and text[start:end] is the cited evidence:
- dates, quantities, prices and party names: `value` is the phrase as written (for example "40 units"); the span
  covers the value, or the short phrase around it for quantities ("minimum order quantity is 40 units");
- clauses (expiry/term, renewal, termination for convenience, exclusivity, minimum commitment, price changes):
  the span is the whole sentence and `value` is that sentence with whitespace collapsed, cut to VALUE_MAX characters.

Limits (measured against CUAD expert labels in study X1, evaluations/extraction_study.py):
- English only, plain text only: uploads are plain text (D-076); PDF intake (text layer, OCR) is not built.
- Patterns, not understanding. A clause worded in an unusual way is missed; a sentence that only mentions a cue can be
  a false hit (common non-clauses such as "non-exclusive" or "sole and exclusive remedy" are excluded, others are not).
- Sentence boundaries are heuristic: full stops after common abbreviations ("Inc.", "Sec.", "U.S.") do not end a
  sentence; very long clauses without full stops are cut at semicolons.
- Dates are returned as written; nothing is normalised and relative terms ("three years from the Effective Date")
  are not resolved. Parties are read from the opening of the document and from "Supplier:"-style labels only.
- At most MAX_PER_FIELD results per field (parties: MAX_PARTIES; effective date: two), in document order. The same
  sentence may support more than one field: a renewal clause often states the term as well, and a minimum-order
  sentence gives both moq (the quantity) and minimum_commitment (the clause), as CUAD counts per-order minimums as
  minimum commitments.
- Headings, tables of contents, definitional cross-references ("has the meaning set forth in") and, for
  exclusivity, recitals ("WHEREAS ...") are not read as clauses.
- Input beyond MAX_CHARS characters is not read (uploads are limited to 1 MB). Every pattern uses bounded repetition.
- Deterministic: the same text always gives the same fields in the same order.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

EXTRACTOR_VERSION = "rules-v1"
FIELDS = ("parties", "agreement_date", "effective_date", "expiry_date", "renewal", "termination_for_convenience",
          "exclusivity", "minimum_commitment", "price", "moq", "lead_time")
MAX_CHARS = 1_000_000
MAX_PER_FIELD = 3
MAX_PARTIES = 8
VALUE_MAX = 280
PREAMBLE = 5_000          # parties and the agreement date are read from the opening of the document
LONG_SENTENCE = 1_500


@dataclass(frozen=True)
class ExtractedField:
    field: str
    value: str
    start: int
    end: int
    source: str = "rule"

    def as_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------------------------------------ sentences
_BOUNDARY = re.compile(r"[.!?][\"'”’)\]]*\s+|\n[ \t\r\f\v]*\n\s*")
_WORD_BEFORE = re.compile(r"([A-Za-z][A-Za-z.]{0,7})$")
_ABBREV = {"inc", "ltd", "corp", "co", "no", "nos", "sec", "secs", "art", "u.s", "u.k", "e.g", "i.e", "etc", "mr",
           "mrs", "ms", "dr", "st", "vs", "approx", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
           "oct", "nov", "dec", "l.l.c", "l.p", "s.a", "n.v", "b.v", "p.c", "fig", "para", "pty", "cf", "viz", "ft"}
_SEMI = re.compile(r";\s+")
_LABEL_LINE = re.compile(r"[ \t]*[A-Z][A-Za-z ]{1,30}:[ \t]")


def sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans [start, end) with surrounding whitespace trimmed; blank lines always end a sentence."""
    raw: list[tuple[int, int]] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        if m.group(0)[0] in ".!?":
            w = _WORD_BEFORE.search(text, max(0, m.start() - 9), m.start())
            if w and (w.group(1).lower() in _ABBREV or (len(w.group(1)) == 1 and w.group(1).isupper())):
                continue
            end = m.start() + len(m.group(0).rstrip())
        else:
            end = m.start()
        raw.append((start, end))
        start = m.end()
    raw.append((start, len(text)))
    out = []
    for a, z in _split_label_lines(text, raw):
        pieces = [(a, z)]
        if z - a > LONG_SENTENCE:                       # a list or schedule without full stops: cut at semicolons
            pieces, at = [], a
            for m in _SEMI.finditer(text, a, z):
                pieces.append((at, m.start() + 1))
                at = m.end()
            pieces.append((at, z))
        for p, q in pieces:
            while p < q and text[p].isspace():
                p += 1
            while q > p and text[q - 1].isspace():
                q -= 1
            if q > p:
                out.append((p, q))
    return out


def _split_label_lines(text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """A line that starts with a label ("Supplier: ...") is a sentence of its own, even without a full stop."""
    out = []
    for a, z in spans:
        lines, at = [], a
        while (nl := text.find("\n", at, z)) != -1:
            lines.append((at, nl))
            at = nl + 1
        lines.append((at, z))
        start = a
        for (p, q), (np_, _) in zip(lines, lines[1:], strict=False):
            if _LABEL_LINE.match(text, p, q) or _LABEL_LINE.match(text, np_, z):
                out.append((start, q))
                start = np_
        out.append((start, z))
    return out


def _clip(s: str) -> str:
    s = " ".join(s.split())
    return s if len(s) <= VALUE_MAX else s[:VALUE_MAX - 1].rstrip() + "…"


# ------------------------------------------------------------------------------------------------ patterns
_MONTH = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
          r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?")
_DAY = r"(?:\d{1,2}(?:st|nd|rd|th)?|_{2,12})"
DATE = (rf"(?:{_MONTH}\s{{1,3}}(?:\d{{1,2}}(?:st|nd|rd|th)?|_{{2,12}}),?\s{{0,3}}\d{{4}}"
        rf"|(?:the\s{{1,3}})?{_DAY}\s{{1,3}}(?:day\s{{1,3}}of\s{{1,3}})?{_MONTH},?\s{{1,3}}\d{{4}}"
        r"|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})")
_DATE = re.compile(DATE, re.I)
_AGREEMENT_CUE = re.compile(r"\b(?:dated|as\s+of|made|entered\s+into|executed|this|on|day\s+of)\b[^.\n]{0,60}$",
                            re.I)
_SOURCE_LINE = re.compile(r"(?:^|\n)[^\n]*source:[^\n]*$", re.I)

_EFFECTIVE = [
    re.compile(rf"({DATE})[^.;\n]{{0,60}}?[\"“]Effective\s+Date[\"”]", re.I),
    re.compile(rf"[\"“]?Effective\s+Date[\"”]?\s*(?:shall\s+mean|means|is|:|of)\s*(?:the\s+)?({DATE})", re.I),
    re.compile(rf"\beffective\s+(?:as\s+of\s+|on\s+|from\s+|date\s+)?(?:the\s+)?({DATE})", re.I),
]
_EFFECTIVE_SENTENCE = re.compile(r"\b(?:shall|will)\s+(?:become|be)\s+effective\b|\bcome\s+into\s+(?:force|effect)\b", re.I)

_EXPIRY = re.compile(
    rf"\b(?:expire[sd]?|terminate[sd]?|end)\s+(?:automatically\s+)?(?:on|at|upon)\s+(?:the\s+)?(?:date|end|expiration|last\s+day"
    rf"|\w+\s+anniversary|{DATE})"
    r"|\b(?:shall|will)\s+(?:continue|remain)\s+(?:in\s+(?:full\s+)?(?:force|effect)\s+)?(?:for|until|through)\b"
    r"|\b(?:shall|will)\s+(?:be|remain)\s+(?:in\s+(?:full\s+)?(?:force|effect)|effective|valid)\s+(?:for|until|through)\b"
    r"|\b(?:is|be|are)\s+valid\s+for\b|\bin\s+effect\s+for\b"
    r"|\b(?:initial\s+)?term\s+(?:of\s+this\s+(?:\w+\s+){0,2}?(?:agreement|contract)\s+)?(?:shall|will)\s+be\b"
    r"|\b(?:for|have)\s+an?\s+(?:initial\s+)?(?:period|term)\s+of\s+(?:\w+\s+){0,3}?\(?\d{1,3}\)?\s*(?:years?|months?)"
    r"|\b(?:shall|will)\s+commence\s+on\b[^.]{0,200}?\b(?:continue|until|years?|months?)\b"
    r"|\b(?:expiration|expiry)\s+date\s+of\s+this\b",
    re.I)
_EXPIRY_SUBJECT = re.compile(r"\b(?:this|the)\s+(?:\w+\s+){0,2}?(?:agreement|contract|amendment|addendum)\b|\bterm\b", re.I)
_EXPIRY_NOT = re.compile(r"\bprovisions?\b[^.]{0,80}?\b(?:continue|remain)\s+in\s+(?:full\s+)?(?:force|effect)"
                         r"|^\W*(?:during|throughout)\s+the\s+term|\bwarrant|\binsurance\b|\bconfidential|\bletter\s+of\s+credit",
                         re.I)

_RENEWAL = re.compile(
    r"\bautomatic(?:ally)?\s+(?:\w+\s+){0,2}?(?:renew|extend|extension)"
    r"|\brenew(?:ed|s|al)?\s+(?:\w+\s+){0,3}?for\s+(?:\w+\s+){0,3}?(?:additional|successive|further|subsequent|consecutive)"
    r"|\brenewal\s+(?:term|period)s?\b"
    r"|\b(?:extended|renewed)\s+(?:\w+\s+){0,3}?for\s+(?:\w+\s+){0,3}?(?:additional|successive|further|subsequent)"
    r"|\bsuccessive\s+(?:\w+\s+){0,4}?(?:periods?|terms?|renewals?)\b",
    re.I)

_TFC_PERMIT = re.compile(
    r"\b(?:may|shall\s+have\s+the\s+right\s+to|ha(?:s|ve)\s+the\s+right\s+to|(?:is|be)\s+entitled\s+to)\s+(?:\w+\s+){0,3}?terminat\w*"
    r"|\bmay\s+(?:\w+\s+){0,2}?be\s+terminated\b|\bright,?\s+(?:\w+\s+){0,8}?to\s+terminat\w*",
    re.I)
_TFC_STRONG = re.compile(
    r"\bwithout\s+(?:any\s+)?cause\b|\bfor\s+(?:its\s+)?convenience\b|\bfor\s+any\s+reason\b|\bfor\s+no\s+reason\b"
    r"|\bany\s+reason\s+or\s+no\s+reason\b|\bin\s+its\s+(?:sole\s+)?discretion\b|\bwith\s+or\s+without\s+cause\b|\bat\s+will\b",
    re.I)
_NOTICE = re.compile(r"\bnotice\b", re.I)
_TFC_NOT = re.compile(r"\bbreach|\bdefault|\binsolven|\bbankrupt|\bfails?\s+to\b|\bfailure\b|\bcure\b|\bchange\s+of\s+control"
                      r"|\bforce\s+majeure|\bmaterial(?:ly)?\b|\bviolat", re.I)

_EXCL = re.compile(r"\bexclusiv\w*", re.I)
_EXCL_NOT = re.compile(
    r"\bnon[\s-]{0,2}exclusiv\w*|\bexclusive\s+of\b|\bexclusive\s+(?:\w+\s+)?(?:remed\w*|liabilit\w*|jurisdiction|venue|forum"
    r"|courts?|property|owner\w*|responsibilit\w*|obligation|statement|warrant\w*|authority|conduct|control"
    r"|right,?\s+title|right\s+to\s+(?:own|control\s+the\s+defen[cs]e))"
    r"|\bexclusively\s+(?:for\s+(?:the\s+)?purposes?|by\s+the\s+laws|governed|in\s+accordance|to\s+the\s+(?:terms|courts?)"
    r"|by\s+(?:a|the)\s+court)|\bbrought\s+exclusively|\bnot\s+intended\s+to\s+be\s+exclusive",
    re.I)
_EXCL_RESTRICT = re.compile(
    r"\bshall\s+not,?\s+(?:directly\s+or\s+indirectly,?\s+)?(?:sell|distribute|appoint|purchase|buy|supply|market|promote)\b"
    r"[^.]{0,160}?"
    r"\b(?:any\s+other|third\s+part\w*|competing|competitive|competitor\w*)",
    re.I)

_MIN_COMMIT = re.compile(
    r"\bminimum\s+(?:annual\s+|quarterly\s+|monthly\s+|yearly\s+)?(?:purchase|order|volume|quantit|commitment"
    r"|sales|amount\s+of\s+(?:product|units)|revenue|number\s+of\s+units|units)\w*"
    r"|\b(?:purchase|order|buy|acquire)\w*\s+(?:\w+\s+){0,4}?(?:at\s+least|no\s+less\s+than|not\s+less\s+than|a\s+minimum\s+of)\b"
    r"|\btake[\s-]or[\s-]pay\b|\bshortfall\b|(?<!non-)(?<!non)\bbinding\s+(?:forecast|commitment|purchase|order)"
    r"|\bfirm\s+(?:purchase\s+)?(?:order|commitment)s?\b",
    re.I)

_MONEY = r"(?:USD|EUR|GBP|AED|US\$|\$|€|£)\s?\d[\d,]*(?:\.\d+)?"
_UNIT = (r"(?:units?|pieces?|pcs|cartons?|cases?|boxes|box|pallets?|kg|kilograms?|tons?|tonnes?|lbs?|pounds?|items?"
         r"|vials?|doses?|bottles?|packs?|each|litres?|liters?|gallons?)")
_PRICE_VALUE = re.compile(rf"\b(?:unit\s+|purchase\s+|supply\s+)?price\s+(?:of\s+|is\s+|:\s*)?({_MONEY}(?:\s+per\s+{_UNIT})?)"
                          rf"|({_MONEY}\s+per\s+{_UNIT})\b", re.I)
_PRICE_CLAUSE = re.compile(
    r"\bprices?\b[^.]{0,200}?\b(?:increas\w*|decreas\w*|adjust\w*|chang\w*|revis\w*|escalat\w*|fixed|firm|reduc\w*"
    r"|not\s+exceed|most\s+favou?red)"
    r"|\b(?:increas\w*|adjust\w*|chang\w*|revis\w*|escalat\w*)\s+(?:\w+\s+){0,3}?(?:the\s+)?prices?\b",
    re.I)

_QTY = r"(?:\w+\s+\()?(\d[\d,]*)\)?\s*"
_MOQ = re.compile(
    rf"\b(?:minimum\s+order(?:\s+quantit(?:y|ies)|\s+size)?|MOQ)\b(?:\s*\(MOQ\))?(?:\s+(?:of|for)\s+[A-Z0-9][\w\-]{{0,40}})?"
    rf"\s*(?:is|of|shall\s+be|will\s+be|becomes|:|=)?\s*{_QTY}({_UNIT})\b",
    re.I)
_LEAD = re.compile(
    rf"\blead[\s-]?times?\b(?:\s+(?:of|is|becomes|shall\s+be|will\s+be|:))?\s*(?:\w+\s+){{0,2}}?{_QTY}"
    r"((?:calendar\s+|business\s+|working\s+)?(?:days?|weeks?|months?))\b"
    rf"|\bdeliver\w*\s+(?:\w+\s+){{0,6}}?within\s+{_QTY}((?:calendar\s+|business\s+|working\s+)?(?:days?|weeks?))\s+"
    r"(?:of|after|from|following)\s+(?:\w+\s+){0,3}?(?:receipt|order|purchase)",
    re.I)

_LABELLED_PARTY = re.compile(
    r"\b(Buyer|Supplier|Seller|Customer|Vendor|Purchaser|Manufacturer|Distributor|Licensor|Licensee|Contractor)\s*:[ \t]*"
    r"(?=[A-Z0-9])")
_MIN_COMMIT_NOT = re.compile(r"\binsurance\b", re.I)
_SKIP_SENTENCE = re.compile(r"\b(?:has|have|shall\s+have)\s+the\s+meanings?\b|\bas\s+defined\s+in\b", re.I)
_SECTION_NO = re.compile(r"\b\d{1,2}\.\d{1,2}\b")
_SUFFIX = (r"(?:Inc|INC|Incorporated|INCORPORATED|LLC|L\.L\.C|Ltd|LTD|Limited|LIMITED|Corp|CORP|Corporation|CORPORATION"
           r"|Company|COMPANY|Co|CO|plc|PLC|GmbH|GMBH|AG|S\.A|SA|S\.p\.A|B\.V|N\.V|L\.P|LP|LLP|Pty|PTY|SE|AB|A/S|Oy|SARL"
           r"|S\.R\.L|Srl|SRL)")
_ENTITY = re.compile(
    rf"\b[A-Z0-9][\w&'\-]{{0,40}}\.?,?\s{{1,3}}(?:(?:[A-Z0-9][\w&'\-]{{0,40}}\.?,?|of|&|the|de|du|la|y)\s{{1,3}}){{0,6}}?"
    rf"{_SUFFIX}\b\.?")
_SHORT_NAME = re.compile(r"\(\s*(?:the\s+|hereinafter\s+(?:referred\s+to\s+as\s+|called\s+)?(?:the\s+)?|each\s+a\s+)?"
                         r"[\"“]([A-Z][A-Za-z0-9&\- ]{1,40}?)[\"”]", re.I)
_NOT_PARTY = {"agreement", "effective date", "territory", "product", "products", "term", "exhibit", "schedule",
              "affiliate", "affiliates", "confidential information", "field", "trademarks", "services", "this agreement"}
_LEAD_WORD = re.compile(r"(?:(?:the|this|a|an|and|by|between|among|whereas|each|such|said|agreement|business|recitals)\b"
                        r"|[A-Z]\.(?=\s))[\s,.]*", re.I)
_PREAMBLE_START = re.compile(r"\b(?:by\s+and\s+between|between|among)\b", re.I)
_NAME_END = re.compile(r"\n|;|\.(?=\s|$)")
_NAME_ABBREV = re.compile(r"(?:Inc|Ltd|Corp|Co|L\.L\.C|S\.A|N\.V|B\.V|L\.P)$")


# ------------------------------------------------------------------------------------------------ rules
def _date_fields(text: str, sents) -> list[ExtractedField]:
    out = []
    head = text[:PREAMBLE]
    for m in _DATE.finditer(head):
        before = head[max(0, m.start() - 80):m.start()]
        if _SOURCE_LINE.search(before) or not _AGREEMENT_CUE.search(before):
            continue
        out.append(ExtractedField("agreement_date", " ".join(m.group(0).split()), m.start(), m.end()))
        break
    eff: list[ExtractedField] = []
    seen = set()
    for pat in _EFFECTIVE:
        for m in pat.finditer(text):
            a, z = m.span(1)
            if (a, z) not in seen:
                seen.add((a, z))
                eff.append(ExtractedField("effective_date", " ".join(m.group(1).split()), a, z))
    if not eff:
        eff = [ExtractedField("effective_date", _clip(text[a:z]), a, z) for a, z in sents
               if _EFFECTIVE_SENTENCE.search(text, a, z)]
    out += sorted(eff, key=lambda f: f.start)[:MAX_PER_FIELD - 1]
    return out


def _clause_sentence(text: str, a: int, z: int) -> bool:
    """False for headings, tables of contents and definitional cross-references, which state no term."""
    if len(text[a:z].split()) < 6 or len(_SECTION_NO.findall(text, a, z)) >= 4:
        return False
    return not _SKIP_SENTENCE.search(text, a, z)


def _sentence_field(text, sents, name, test) -> list[ExtractedField]:
    out = []
    for a, z in sents:
        if _clause_sentence(text, a, z) and test(text, a, z):
            out.append(ExtractedField(name, _clip(text[a:z]), a, z))
            if len(out) == MAX_PER_FIELD:
                break
    return out


def _expiry(text, a, z):
    return bool(_EXPIRY.search(text, a, z) and _EXPIRY_SUBJECT.search(text, a, z) and not _EXPIRY_NOT.search(text[a:z]))


def _tfc(text, a, z):
    if not _TFC_PERMIT.search(text, a, z):
        return False
    if _TFC_STRONG.search(text, a, z):
        return True
    return bool(_NOTICE.search(text, a, z)) and not _TFC_NOT.search(text, a, z)


def _min_commit(text, a, z):
    return bool(_MIN_COMMIT.search(text, a, z)) and not _MIN_COMMIT_NOT.search(text, a, z)


def _exclusive(text, a, z):
    s = text[a:z]
    if s.lstrip().upper().startswith("WHEREAS"):                      # recitals describe, they do not grant
        return False
    hits = [m.start() for m in _EXCL.finditer(s)]
    bad = {m.start() + (m.group(0).lower().find("exclusiv")) for m in _EXCL_NOT.finditer(s)}
    if any(h not in bad for h in hits):
        return True
    return bool(_EXCL_RESTRICT.search(s))


def _price(text, a, z):
    return bool(_PRICE_CLAUSE.search(text, a, z))


def _quantity_fields(text: str, name: str, pat: re.Pattern) -> list[ExtractedField]:
    out = []
    for m in pat.finditer(text):
        groups = [i for i in range(1, (pat.groups or 0) + 1) if m.group(i) is not None]
        if len(groups) < 2:
            continue
        value = " ".join(f"{m.group(groups[0])} {m.group(groups[1])}".split())
        out.append(ExtractedField(name, value, m.start(), m.end()))
        if len(out) == MAX_PER_FIELD:
            break
    return out


def _prices(text: str, sents) -> list[ExtractedField]:
    out = []
    for m in _PRICE_VALUE.finditer(text):
        g = 1 if m.group(1) is not None else 2
        a, z = m.span(g)
        out.append(ExtractedField("price", " ".join(m.group(g).split()), a, z))
    out += [f for f in _sentence_field(text, sents, "price", _price)
            if not any(p.start >= f.start and p.end <= f.end for p in out)]
    return sorted(out, key=lambda f: f.start)[:MAX_PER_FIELD]


def _name_at(text: str, start: int, limit: int) -> tuple[int, int]:
    """A party name written after a label: up to the line end, a semicolon or a full stop that is not an abbreviation."""
    end = min(len(text), start + 200, limit)
    for m in _NAME_END.finditer(text, start, end):
        if m.group(0) == "." and _NAME_ABBREV.search(text, max(start, m.start() - 6), m.start()):
            continue
        end = m.start()
        break
    while end > start and text[end - 1] in " \t,.":
        end -= 1
    return start, end


def _parties(text: str) -> list[ExtractedField]:
    head = text[:PREAMBLE]
    found: list[tuple[int, int]] = []
    for m in _LABELLED_PARTY.finditer(head):
        a, z = _name_at(head, m.end(), len(head))
        if z - a >= 2:
            found.append((a, z))
    pm = _PREAMBLE_START.search(head)
    a0 = pm.start() if pm else 0
    window = (a0, min(len(head), a0 + 1_500))
    for m in _ENTITY.finditer(head, *window):
        a, z = m.start(), m.end()
        while (lw := _LEAD_WORD.match(head, a, z)) and lw.end() > a:
            a = lw.end()
        while z > a and head[z - 1] in " ,":
            z -= 1
        if len(head[a:z].split()) < 2:                                # a bare suffix such as "Company" is not a name
            continue
        found.append((a, z))
        sm = _SHORT_NAME.search(head, z, min(len(head), z + 250))
        if sm and not _ENTITY.search(head, z, sm.start()) and sm.group(1).strip().lower() not in _NOT_PARTY:
            found.append(sm.span(1))
    out: list[ExtractedField] = []
    for a, z in sorted(set(found), key=lambda s: (s[0], -s[1])):
        if any(not (z <= f.start or a >= f.end) for f in out):     # overlapping mentions: keep the first, longest
            continue
        out.append(ExtractedField("parties", " ".join(head[a:z].split()), a, z))
        if len(out) == MAX_PARTIES:
            break
    return out


def extract(text: str) -> list[ExtractedField]:
    """Draft fields found in `text`, ordered by FIELDS and then by position. Deterministic; never raises on odd input."""
    text = (text or "")[:MAX_CHARS]
    if not text.strip():
        return []
    sents = sentences(text)
    found = (
        _parties(text)
        + _date_fields(text, sents)
        + _sentence_field(text, sents, "expiry_date", _expiry)
        + _sentence_field(text, sents, "renewal", lambda t, a, z: bool(_RENEWAL.search(t, a, z)))
        + _sentence_field(text, sents, "termination_for_convenience", _tfc)
        + _sentence_field(text, sents, "exclusivity", _exclusive)
        + _sentence_field(text, sents, "minimum_commitment", _min_commit)
        + _prices(text, sents)
        + _quantity_fields(text, "moq", _MOQ)
        + _quantity_fields(text, "lead_time", _LEAD)
    )
    order = {f: i for i, f in enumerate(FIELDS)}
    return sorted(found, key=lambda f: (order[f.field], f.start, f.end))
