"""Γ dla grafu ograniczeń (M2) i strefa wpływu.

Elementy R: {"id": "G1", "type": "requires|excludes|precedes", "from": x, "to": y, "source": ...}.
Węzłami są stany, zdarzenia i warunki ze słownika.
"""
from collections import defaultdict


def _requires_paths(edges):
    """Domknięcie przechodnie relacji 'requires': {x: {y: [krawędzie na ścieżce x -> y]}}."""
    out = defaultdict(list)
    for e in edges:
        if e["type"] == "requires":
            out[e["from"]].append(e)
    closure = {}
    for x in list(out):
        paths, todo = {}, [(x, [])]
        while todo:
            node, path = todo.pop()
            for e in out[node]:
                if e["to"] not in paths:
                    paths[e["to"]] = path + [e]
                    todo.append((e["to"], path + [e]))
        closure[x] = paths
    return closure


def _precedes_cycles(edges):
    """Cykle w relacji 'precedes' (każdy jako lista krawędzi), wyszukiwane przez DFS."""
    out = defaultdict(list)
    for e in edges:
        if e["type"] == "precedes":
            out[e["from"]].append(e)
    cycles, done = [], set()

    def dfs(node, path, on_path):
        for e in out[node]:
            if e["to"] in on_path:
                start = next(i for i, p in enumerate(path + [e]) if p["from"] == e["to"])
                cycles.append((path + [e])[start:])
            elif e["to"] not in done:
                dfs(e["to"], path + [e], on_path | {e["to"]})
        done.add(node)

    for node in list(out):
        if node not in done:
            dfs(node, [], {node})
    return cycles


def check(scaffold):
    """Zwraca listę konfliktów: {"rule": opis, "items": [krawędzie]}."""
    edges = scaffold["R"]
    closure = _requires_paths(edges)
    excludes = {}
    for e in edges:
        if e["type"] == "excludes":
            excludes[frozenset((e["from"], e["to"]))] = e

    found = {}

    def add(rule, items):
        key = frozenset(i["id"] for i in items)
        found.setdefault(key, {"rule": rule, "items": items})

    for x, paths in closure.items():
        for y, path in paths.items():
            ex = excludes.get(frozenset((x, y)))
            if ex:
                add(f"{x} requires+ {y}, ale {x} excludes {y}", path + [ex])
        targets = sorted(paths)
        for i, y in enumerate(targets):
            for z in targets[i + 1:]:
                ex = excludes.get(frozenset((y, z)))
                if ex:
                    add(f"{x} requires+ {y} i {z}, ale {y} excludes {z}", paths[y] + paths[z] + [ex])
    for cycle in _precedes_cycles(edges):
        add("cykl w relacji precedes: " + " -> ".join(e["from"] for e in cycle), cycle)
    return list(found.values())


def influence_zone(scaffold, changed_items):
    """Węzły połączone (w dowolnym kierunku) ze zmienionymi elementami.

    Zmienione elementy to krawędzie R i decyzje D (stare i nowe wersje).
    Krawędzie usunięte też łączą węzły, bo ich usunięcie dotyczy obu końców.
    """
    start = set()
    for item in changed_items:
        if "transition" in item:
            start |= {x for x in item["transition"] if x is not None}
        elif "type" in item:
            start |= {item["from"], item["to"]}
    neighbours = defaultdict(set)
    for e in scaffold["R"] + [i for i in changed_items if "type" in i]:
        neighbours[e["from"]].add(e["to"])
        neighbours[e["to"]].add(e["from"])
    zone, todo = set(start), list(start)
    while todo:
        for n in neighbours[todo.pop()]:
            if n not in zone:
                zone.add(n)
                todo.append(n)
    return zone
