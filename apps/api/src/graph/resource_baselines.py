"""Resource consumption baselines and anomaly checks from Neo4j."""

from __future__ import annotations

import math

from src.stores import GraphDB


def fetch_baselines(
    db: GraphDB,
    agent_name: str,
    exclude_thread_id: str | None = None,
    min_samples: int = 3,
) -> dict | None:
    """Historical mean/std for total_tokens and total_cost for a node name.

    Excludes exclude_thread_id when computing stats. Returns None if sample_count < min_samples.
    """
    params: dict = {"name": agent_name}
    where_exclude = " AND n.thread_id <> $exclude_thread_id" if exclude_thread_id else ""
    if exclude_thread_id:
        params["exclude_thread_id"] = exclude_thread_id

    query = (
        "MATCH (n) WHERE n.name = $name AND (n:Agent OR n:Tool)" + where_exclude + " "
        "WITH n "
        "RETURN avg(n.total_tokens) AS mean_tokens, stdev(n.total_tokens) AS std_tokens, "
        "avg(n.total_cost) AS mean_cost, stdev(n.total_cost) AS std_cost, count(n) AS sample_count"
    )
    rows = db.query(query, parameters=params)
    if not rows:
        return None
    r = rows[0]
    sample_count = r.get("sample_count") or 0
    if sample_count < min_samples:
        return None
    mean_tokens = r.get("mean_tokens")
    std_tokens = r.get("std_tokens")
    mean_cost = r.get("mean_cost")
    std_cost = r.get("std_cost")
    return {
        "mean_tokens": mean_tokens if mean_tokens is not None else 0.0,
        "std_tokens": std_tokens if std_tokens is not None and not math.isnan(std_tokens) else 0.0,
        "mean_cost": mean_cost if mean_cost is not None else 0.0,
        "std_cost": std_cost if std_cost is not None and not math.isnan(std_cost) else 0.0,
        "sample_count": sample_count,
    }


def check_resource_anomalies(
    db: GraphDB,
    thread_id: str,
    z_threshold: float = 2.5,
    min_samples: int = 3,
) -> list[dict]:
    """Compare this thread's Agent/Tool node usage to historical baselines; return anomalies."""
    node_rows = db.query(
        "MATCH (n) WHERE n.thread_id = $thread_id AND (n:Agent OR n:Tool) "
        "RETURN n.name AS name, n.total_tokens AS total_tokens, n.total_cost AS total_cost",
        parameters={"thread_id": thread_id},
    )
    anomalies: list[dict] = []
    for row in node_rows:
        name = row.get("name")
        if not name:
            continue
        total_tokens = row.get("total_tokens")
        total_cost = row.get("total_cost")
        if total_tokens is None:
            total_tokens = 0
        if total_cost is None:
            total_cost = 0.0

        base = fetch_baselines(db, name, exclude_thread_id=thread_id, min_samples=min_samples)
        if base is None:
            continue

        def z_score(value: float, mean: float, std: float) -> float | None:
            if std is None or std <= 0 or not math.isfinite(std):
                return None
            if not math.isfinite(value) or not math.isfinite(mean):
                return None
            return (value - mean) / std

        z_tokens = z_score(
            float(total_tokens),
            base["mean_tokens"],
            base["std_tokens"],
        )
        if z_tokens is not None and z_tokens > z_threshold:
            anomalies.append({
                "node_name": name,
                "metric": "total_tokens",
                "value": float(total_tokens),
                "mean": base["mean_tokens"],
                "std": base["std_tokens"],
                "z_score": round(z_tokens, 2),
            })

        z_cost = z_score(
            float(total_cost),
            base["mean_cost"],
            base["std_cost"],
        )
        if z_cost is not None and z_cost > z_threshold:
            anomalies.append({
                "node_name": name,
                "metric": "total_cost",
                "value": float(total_cost),
                "mean": base["mean_cost"],
                "std": base["std_cost"],
                "z_score": round(z_cost, 2),
            })

    return anomalies
