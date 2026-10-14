"""lxml helpers. Elements are matched by local name so namespace URIs and prefixes,
which may differ between HANA versions, never affect parsing."""
from __future__ import annotations

from lxml import etree

XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

_PARSER_OPTIONS = dict(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


def load(data: bytes) -> tuple[etree._Element | None, str | None, int | None]:
    """Parse bytes. Returns (root, None, None) or (None, message, line)."""
    try:
        return etree.fromstring(data, etree.XMLParser(**_PARSER_OPTIONS)), None, None
    except etree.XMLSyntaxError as exc:
        return None, str(exc), exc.lineno
    except ValueError as exc:  # e.g. unicode strings with an encoding declaration
        return None, str(exc), None


def local(el: etree._Element) -> str:
    return etree.QName(el).localname


def _is_element(node) -> bool:
    return isinstance(node.tag, str)  # comments and processing instructions are not


def children(el: etree._Element | None, name: str | None = None) -> list[etree._Element]:
    if el is None:
        return []
    return [c for c in el if _is_element(c) and (name is None or local(c) == name)]


def child(el: etree._Element | None, name: str) -> etree._Element | None:
    found = children(el, name)
    return found[0] if found else None


def descendants(el: etree._Element | None, name: str) -> list[etree._Element]:
    if el is None:
        return []
    return [d for d in el.iterdescendants() if _is_element(d) and local(d) == name]


def first_descendant(el: etree._Element | None, name: str) -> etree._Element | None:
    found = descendants(el, name)
    return found[0] if found else None


def text(el: etree._Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    return el.text.strip()


def xsi_type_name(el: etree._Element) -> str | None:
    """Local part of xsi:type, e.g. "Calculation:JoinView" -> "JoinView"."""
    value = el.get(f"{{{XSI_NS}}}type")
    if value is None:
        return None
    return value.rpartition(":")[2]


def raw(el: etree._Element) -> str:
    return etree.tostring(el, encoding="unicode", with_tail=False)
