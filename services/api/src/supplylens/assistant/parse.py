"""Pure text rules for the status assistant: no database, no model. Every rule is a regular expression or a word list,
so the same question always gets the same reading (and evaluations/assistant_study.py can measure the rules alone).

Order of use (answer.py): a question that asks to change anything is withheld first, before any lookup, even when it
names a real record ("cancel order SBX-PO-3"); then questions outside the assistant's scope (secrets, instructions to the
assistant); then identifiers (action ids, purchase-order numbers, product codes); then product-description words.
"""
from __future__ import annotations

import re

UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
PO_RE = re.compile(r"\b[a-z]{2,6}-po-\d{1,12}\b", re.I)          # sandbox ERP numbers look like SBX-PO-12
HEX_PREFIX_RE = re.compile(r"^[0-9a-f]{8,32}$", re.I)            # the first characters of an action id
_TOKEN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_\-./]*[A-Za-z0-9])?")
_WORD_RE = re.compile(r"[a-z0-9]+")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ------------------------------------------------------------------------------------------ change requests (withheld)
_PREAMBLE = (r"(?:please\s+|pls\s+|kindly\s+|now\s+|just\s+|then\s+|ok(?:ay)?,?\s+|hey,?\s+|go\s+ahead\s+and\s+|let'?s\s+|"
             r"help\s+me\s+(?:to\s+)?|(?:can|could|would|will)\s+you\s+(?:please\s+)?|"
             r"i\s+(?:want|need|wish|would\s+like|'d\s+like)\s+(?:you\s+)?to\s+|i'?m\s+going\s+to\s+)*")
# "set" is a verb unless it starts a product name ("SET OF 3 CAKE TINS"); adjectives that also start product names
# (double, mini) are not in this list and are caught only with a value to change (rules below).
_VERBS = (r"cancel|approve|reject|decline|delete|remove|erase|modify|edit|update|change|alter|increase|decrease|reduce|"
          r"raise|lower|adjust|override|set(?!\s+of\b)|reset|reorder|re-order|buy|purchase|place|submit|send|dispatch|"
          r"release|refund|pay|transfer|move|book|receive|mark|create|add|make|draft|prepare|retry|reconcile|accept|sign|"
          r"lock|unlock|assign|close|reopen|rename|replace|expedite|ship|archive|restore|upload|import")
_RULES = [
    # an imperative at the start: "approve it", "could you update the lead time", "please set the MOQ"
    re.compile(r"^\W*" + _PREAMBLE + r"(?:" + _VERBS + r")\b", re.I),
    # "order 50 units", "I want to order more", "reorder SYN001"
    re.compile(r"^\W*" + _PREAMBLE + r"order\s+(?:\d|more|some|another|an?\b|new|extra|additional|again)", re.I),
    re.compile(r"\b(?:order|buy|get)\s+(?:\d+|more|some|another|extra|additional)\s+(?:units?|pcs|pieces|of|more|cases?|packs?)\b",
               re.I),
    # verbs that never belong to a status question, wherever they stand
    re.compile(r"\b(?:cancel|approve|reject|delete|remove|erase|override|refund|reorder|re-order|expedite|buy)\b", re.I),
    re.compile(r"\bpurchase\b(?![\s-]+orders?\b)", re.I),         # "purchase order SBX-PO-3", "purchase-order draft": nouns
    # change a named value: "change the price", "increase its MOQ", "update the order status"
    re.compile(r"\b(?:set|change|update|edit|modify|alter|increase|decrease|reduce|raise|lower|adjust|reset|bump|cut|halve|"
               r"double)\s+(?:the\s+|its\s+|this\s+|that\s+|our\s+|my\s+|their\s+|a\s+)?(?:unit\s+|purchase\s+|order\s+)?"
               r"(?:price|prices|cost|costs|quantity|quantities|qty|moq|minimum|lead[\s-]*times?|stock|order|orders|status|"
               r"pack[\s-]*sizes?|terms?|supplier|budget|approval|draft|po|inventory|forecast|safety)\b", re.I),
    re.compile(r"\b(?:set|change|update|edit|modify|increase|decrease|reduce|raise|lower|adjust)\b.*\b(?:to|by)\s+[£$€]?\d", re.I),
    re.compile(r"\b(?:place|submit|send|create|raise|draft|prepare|make|issue)\s+(?:a\s+|an\s+|the\s+|new\s+|another\s+|my\s+|"
               r"our\s+|this\s+|that\s+)*(?:purchase[\s-]+)?(?:order|po|draft|requisition)s?\b", re.I),
    re.compile(r"\bmark\b.*\bas\s+(?:received|approved|paid|cancell?ed|shipped|done|complete|delivered)\b", re.I),
]

# ------------------------------------------------------------------------------------------ outside the scope (withheld)
_UNSAFE = re.compile(
    r"ignore\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier|preceding)|disregard\s+(?:all|any|the|your)|"
    r"system\s+prompt|your\s+(?:instructions|prompt|rules)|\bjailbreak|developer\s+mode|pretend\s+(?:you|to)|act\s+as\b|"
    r"api[\s_-]*keys?|access[\s_-]*tokens?|\btokens?\b|\bpasswords?\b|\bsecrets?\b|\bcredentials?\b|private\s+key|"
    r"environment\s+variables?|\benv\b", re.I)

# ------------------------------------------------------------------------------------------ what is asked
_TERMS = re.compile(
    r"lead[\s-]*times?|\bmoq\b|minimum\s+order|\bmin(?:imum)?\.?\s+(?:order|qty|quantity)|pack[\s-]*sizes?|order\s+multiples?|"
    r"\bmultiples?\b|case\s+size|batch\s+size|smallest\s+order|\bsuppliers?\b|\bterms?\b|delivery\s+time|how\s+long|"
    r"\bdeliver|\bquote", re.I)
_STOCK = re.compile(
    r"\bstock|\bavailab|\binventory|on\s+hand|\bcover\b|\bhealth|\bleft\b|how\s+many|\bshortage|\bexcess|\bunits?\b|"
    r"\bopen\s+orders?|on\s+order|\bquantity", re.I)
_ORDER = re.compile(r"\border|\bpo\b|\bdraft|\baction|\bapprov|\bstatus", re.I)

STOP = frozenset("""
a an the of for to in on at by with from and or is are was were be been being do does did done we i you our my me us it its
this that these those what whats which who whom when where why how much many any some there here have has had can could
would will should shall may might must please tell show give find get know about current currently right now today still
left s t d ll re ve m stock stocks stocked available availability inventory hand cover covered days day health healthy
status state order orders ordered ordering open po pos purchase lead time times leadtime moq minimum min pack packs size
sizes multiple multiples case batch supplier suppliers vendor vendors terms term units unit item items sku skus product
products code codes level levels quantity qty delivery deliver delivered long take takes force approval approved draft
drafts action actions risk shortage excess need needs more than per as if not no yes look looking like up out latest
warehouse warehouses location locations site store shelf shelves we've got have smallest quote quoted expected arriving
arrive due on-hand there's what's is it's info information details detail check checking see view much
""".split())


def is_mutation(question: str) -> bool:
    """True when the question asks the assistant to change, create or decide anything."""
    q = " ".join(question.split())
    return any(r.search(q) for r in _RULES)


def is_unsafe(question: str) -> bool:
    """True for requests about secrets or instructions to the assistant itself: never answered from records."""
    return bool(_UNSAFE.search(question))


def wants_terms(question: str) -> bool:
    return bool(_TERMS.search(question))


def wants_stock(question: str) -> bool:
    return bool(_STOCK.search(question))


def mentions_records(question: str) -> bool:
    """Words that show the question is about stock, terms or orders (a miss is then "no match", not "out of scope")."""
    return bool(_TERMS.search(question) or _STOCK.search(question) or _ORDER.search(question))


def uuids(question: str) -> list[str]:
    return _unique(m.lower() for m in UUID_RE.findall(question))


def po_numbers(question: str) -> list[str]:
    return _unique(m.upper() for m in PO_RE.findall(question))


def candidate_codes(question: str) -> list[str]:
    """Tokens that look like record identifiers: letters with digits (SYN001, 85123A), five or more digits (20724), eight or
    more hex characters (the start of an action id), or upper-case codes with hyphens (DEMO-REF-SKU). Quantities, short
    numbers, dates, full ids and PO numbers are not codes."""
    skip = {u.lower() for u in uuids(question)} | {p.upper() for p in po_numbers(question)}
    out = []
    for raw in _TOKEN_RE.findall(question):
        tok = raw.strip("-./_")
        if not tok or tok.lower() in skip or tok.upper() in skip or _DATE_RE.match(tok) or UUID_RE.fullmatch(tok):
            continue
        has_digit, has_alpha = any(c.isdigit() for c in tok), any(c.isalpha() for c in tok)
        if (has_digit and has_alpha and len(tok) >= 3) or (tok.isdigit() and len(tok) >= 5) or HEX_PREFIX_RE.match(tok) \
                or ("-" in tok and any(c.isupper() for c in tok) and len(tok) >= 5):
            out.append(tok.upper())
    return _unique(out)


def content_words(question: str, drop: set[str] | None = None) -> list[str]:
    """Words left after removing function words, the assistant's own vocabulary and `drop` (identifier and supplier
    words): what may describe a product ("white hanging heart", "synthetic product 12")."""
    drop = {d.lower() for d in (drop or set())}
    return _unique(w for w in _WORD_RE.findall(question.lower()) if w not in STOP and w not in drop)


def describes(words: list[str]) -> bool:
    """A description search needs at least one real word (not only numbers): "stock for 7" is not a product."""
    return any(w.isalpha() and len(w) >= 3 for w in words)


def _unique(items) -> list[str]:
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out
