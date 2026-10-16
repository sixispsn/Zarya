"""Loss-coverage manifests from the actual VU/station graph, not the drawing.

This enumerates candidate paths, NOT a hydraulic solution of parallel pipes.
No source pressure, flow split, length, valve Kv or zero loss is inferred.
"""


def suction_path_manifest(network, pump_ids, closed, *, path_limit=16, search_limit=4096):
    if network is None:
        return dict(status="unsupported", routes=[], complete=False)
    network.validate()
    nodes = {n.id: n for n in network.nodes}
    pumps, blocked = set(pump_ids), set(closed)
    if not pumps or not pumps <= nodes.keys() or not blocked <= nodes.keys():
        raise ValueError("Неизвестный насос или закрытый элемент пути")
    if path_limit < 1 or search_limit < 1:
        raise ValueError("Предел поиска должен быть положительным")
    sources = sorted(n.id for n in network.nodes if n.kind == 'source' and
                     (n.id.startswith('supply_source_') or n.id == 'inlet'))
    adjacency = {n: set() for n in nodes}
    for edge in network.links:
        adjacency[edge.a].add(edge.b)
        adjacency[edge.b].add(edge.a)
    if any(n.kind == 'check' and not n.forward_to for n in network.nodes):
        raise ValueError("Не задано направление обратного клапана")
    routes, complete = [], True
    for source in sources:
        for pump in sorted(pumps):
            paths, stack, visits = [], [(source,)], 0
            while stack:
                if len(paths) >= path_limit or visits >= search_limit:
                    complete = False
                    break
                path = stack.pop()
                current = path[-1]
                visits += 1
                if current in blocked:
                    continue
                if current == pump:
                    paths.append(path)
                    continue
                if current in pumps or (current != source and nodes[current].kind == 'source'):
                    continue
                node = nodes[current]
                neighbours = {node.forward_to} if node.kind == 'check' else adjacency[current]
                for nxt in sorted(neighbours, reverse=True):
                    if nxt in path or nxt in blocked:
                        continue
                    if nodes[nxt].kind == 'check' and current == nodes[nxt].forward_to:
                        continue
                    stack.append((*path, nxt))
            for path in paths:
                # Every inline body and connection must be covered, possibly
                # by ONE grouped pipe/local-loss result. Boundary/pump bodies
                # are outside the suction loss path, but their links are not.
                components = ["node:" + n for n in path[1:-1]]
                components += ["link:" + a + "->" + b for a, b in zip(path, path[1:])]
                routes.append(dict(source=source, pump=pump, nodes=list(path),
                    required_components=components, metered='meter' in path,
                    total_loss_m=None, status="needs_data"))
    return dict(status="needs_data" if complete and routes else "unsupported",
        routes=routes, complete=complete, closed_components=sorted(blocked),
        notes=["Это альтернативные пути, их потери не складываются между собой.",
               "Распределение расходов между открытыми вводами/ветвями не рассчитано; Q/2 не назначается.",
               "Состав берётся из текущего графа. Потери, режим и граница давления требуют явной привязки.",
               "Путь заканчивается на всасывании: насос, напорная арматура и квартирные узлы в Hf не входят."])
