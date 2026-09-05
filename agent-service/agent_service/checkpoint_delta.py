"""Versioned state replication; replaying it performs no model or tool calls."""
from copy import deepcopy


def recovery_projection(data):
    result = {k: deepcopy(v) for k, v in data.items()
              if k not in {"events", "event_base_seq", "last_acked_seq"}
              and not k.startswith("recovery_")}
    result.update(events=[], event_base_seq=data.get("event_base_seq", 0) + len(data["events"]),
                  last_acked_seq=0)
    return result


def changes(before, after, path=()):
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        result = [{"op": "remove", "path": [*path, key]} for key in before.keys() - after.keys()]
        for key, value in after.items():
            if key in before:
                result.extend(changes(before[key], value, (*path, key)))
            else:
                result.append({"op": "set", "path": [*path, key], "value": deepcopy(value)})
        return result
    if isinstance(before, (str, list)) and type(before) is type(after) and after[:len(before)] == before:
        return [{"op": "append", "path": list(path), "value": deepcopy(after[len(before):])}]
    return [{"op": "set", "path": list(path), "value": deepcopy(after)}]


def apply_changes(before, operations):
    result = deepcopy(before)
    for item in operations:
        path, op = item.get("path"), item.get("op")
        if not isinstance(path, list) or not all(isinstance(p, str) for p in path):
            raise ValueError("RT.SESSION.INVALID_DELTA")
        if not path:
            if op != "set" or not isinstance(item.get("value"), dict):
                raise ValueError("RT.SESSION.INVALID_DELTA")
            result = deepcopy(item["value"])
            continue
        parent = result
        for key in path[:-1]:
            if not isinstance(parent, dict) or not isinstance(parent.get(key), dict):
                raise ValueError("RT.SESSION.INVALID_DELTA")
            parent = parent[key]
        if not isinstance(parent, dict):
            raise ValueError("RT.SESSION.INVALID_DELTA")
        key = path[-1]
        if op == "set" and "value" in item:
            parent[key] = deepcopy(item["value"])
        elif op == "remove" and key in parent:
            del parent[key]
        elif op == "append" and isinstance(parent.get(key), (str, list)) and type(parent[key]) is type(item.get("value")):
            parent[key] += deepcopy(item["value"])
        else:
            raise ValueError("RT.SESSION.INVALID_DELTA")
    return result


def update_journal(data):
    current = recovery_projection(data)
    previous = data.get("recovery_state", {})
    delta = changes(previous, current)
    if not delta:
        return
    base = data.get("recovery_version", 0)
    data["recovery_version"] = base + 1
    data["recovery_state"] = current
    data["recovery_journal"] = (data.get("recovery_journal", []) + [
        {"base_version": base, "version": base + 1, "changes": delta}])[-32:]


def recovery_page(data, version):
    latest = data.get("recovery_version", 0)
    journal = data.get("recovery_journal", [])
    selected = [item for item in journal if item["version"] > version]
    if version > 0 and version <= latest and (version == latest or selected and selected[0]["base_version"] == version):
        return {"version": latest, "deltas": selected}
    return {"version": latest, "checkpoint": recovery_projection(data)}
