from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from . import db

def export_all(database: db.Database, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rels = database.all_relations()
    edges = [(r["from_sig"], r["to_sig"], r["kind"], r["source"], r["raw"] or "")
             for r in rels]
    nodes = sorted({e[0] for e in edges} | {e[1] for e in edges})

    paths = {
        "csv": _csv(edges, out_dir / "relations.csv"),
        "json": _json(nodes, edges, out_dir / "relations.json"),
        "graphml": _graphml(nodes, edges, out_dir / "relations.graphml"),
    }
    return paths

def _csv(edges, path: Path) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["from_sig", "to_sig", "kind", "source", "raw"])
        w.writerows(edges)
    return path

def _json(nodes, edges, path: Path) -> Path:
    data = {
        "nodes": [{"id": n} for n in nodes],
        "edges": [
            {"from": f, "to": t, "kind": k, "source": s, "raw": raw}
            for (f, t, k, s, raw) in edges
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

def _graphml(nodes, edges, path: Path) -> Path:
    ns = "http://graphml.graphdrawing.org/xmlns"
    ET.register_namespace("", ns)
    root = ET.Element(f"{{{ns}}}graphml")

    for key_id, attr_name in (("d_kind", "kind"), ("d_source", "source")):
        k = ET.SubElement(root, f"{{{ns}}}key")
        k.set("id", key_id)
        k.set("for", "edge")
        k.set("attr.name", attr_name)
        k.set("attr.type", "string")

    graph = ET.SubElement(root, f"{{{ns}}}graph")
    graph.set("edgedefault", "directed")

    for n in nodes:
        node = ET.SubElement(graph, f"{{{ns}}}node")
        node.set("id", n)

    for i, (f, t, kind, source, _raw) in enumerate(edges):
        edge = ET.SubElement(graph, f"{{{ns}}}edge")
        edge.set("id", f"e{i}")
        edge.set("source", f)
        edge.set("target", t)
        for key_id, val in (("d_kind", kind), ("d_source", source)):
            d = ET.SubElement(edge, f"{{{ns}}}data")
            d.set("key", key_id)
            d.text = val

    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path
