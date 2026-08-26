from collections import defaultdict, deque
from uuid import UUID


def collect_dependent_artifacts(
    edges: list[tuple[UUID, UUID]],
    changed_artifact_ids: set[UUID],
    locked_artifact_ids: set[UUID] | None = None,
) -> set[UUID]:
    locked = locked_artifact_ids or set()
    graph: dict[UUID, list[UUID]] = defaultdict(list)
    for upstream_id, downstream_id in edges:
        graph[upstream_id].append(downstream_id)

    stale: set[UUID] = set()
    queue = deque(changed_artifact_ids)
    while queue:
        current = queue.popleft()
        for downstream_id in graph[current]:
            if downstream_id in stale or downstream_id in locked:
                continue
            stale.add(downstream_id)
            queue.append(downstream_id)
    return stale
