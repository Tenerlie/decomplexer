from __future__ import annotations

CONTROL = "Control"
SEARCH_PAGE = "Control?todo=szukajAkt"

SEARCH_DEFAULTS: dict[str, str] = {
    "todo": "znajdzAkt",
    "Offset": "0",
    "Tekst": "",
    "Gdzie": "2",
    "status": "0",
    "Lacznik": "AND",
    "Odstep": "0",
    "rokOD": "",
    "MiesiacOD": "",
    "DzienOD": "",
    "RokDO": "",
    "MiesiacDo": "",
    "Litera": "",
    "Numer": "",
    "Rok": "",
    "Limit": "100",
    "Sort": "4",
    "Rodzaj": "",
    "Organ": "",
    "Podmiot": "",
    "Kategoria": "",
    "ZmieniajacyLitera": "",
    "ZmieniajacyNumer": "",
    "ZmieniajacyRok": "",
    "ZmienianyLitera": "",
    "ZmienianyNumer": "",
    "ZmienianyRok": "",
    "search": "szukaj",
}

NEXT_PAGE_DATA: dict[str, str] = {
    "todo": "pokazStrone",
    "what": "next",
    "next": ">>> next",
}

SEARCH_SUBMIT = 'input[name="search"]'
NEXT_BUTTON = 'input[name="next"]'
