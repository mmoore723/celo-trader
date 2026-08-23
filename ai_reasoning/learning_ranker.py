"""Small auditable shadow ranker for learning episodes; never read by orders."""
from __future__ import annotations

import json
import math
from datetime import datetime
from uuid import uuid4

MIN_EPISODES = 1000
FEATURES = ("bias", "confidence", "bullish", "hour", "episode_size")


def _vector(example: dict) -> list[float]:
    observed = datetime.fromisoformat(str(example["observed_at"]).replace("Z", "+00:00"))
    return [1.0, float(example.get("confidence") or 0),
            1.0 if str(example.get("direction")).lower() == "bullish" else 0.0,
            observed.hour / 24.0, min(float(example.get("episode_size") or 1), 10.0) / 10.0]


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))


def _auc(labels: list[int], scores: list[float]) -> float | None:
    positives = [score for label, score in zip(labels, scores) if label == 1]
    negatives = [score for label, score in zip(labels, scores) if label == 0]
    if not positives or not negatives:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def train_shadow_model(examples: list[dict]) -> dict:
    usable = [item for item in examples if item.get("direction_correct") in (0, 1)]
    usable.sort(key=lambda item: item["observed_at"])
    if len(usable) < MIN_EPISODES:
        return {"status": "collecting", "usable_episodes": len(usable), "required": MIN_EPISODES,
                "order_authority": False}
    split = max(1, int(len(usable) * 0.8)); train, holdout = usable[:split], usable[split:]
    weights = [0.0] * len(FEATURES)
    for epoch in range(350):
        rate = 0.08 / (1 + epoch / 100)
        gradient = [0.0] * len(weights)
        for item in train:
            vector = _vector(item); error = _sigmoid(sum(w*x for w, x in zip(weights, vector))) - int(item["direction_correct"])
            for index, value in enumerate(vector): gradient[index] += error * value
        for index in range(len(weights)):
            weights[index] -= rate * gradient[index] / len(train)
    labels = [int(item["direction_correct"]) for item in holdout]
    scores = [_sigmoid(sum(w*x for w, x in zip(weights, _vector(item)))) for item in holdout]
    auc = _auc(labels, scores)
    qualified = len(holdout) >= 100 and len(set(labels)) == 2 and auc is not None and auc >= 0.52
    metrics = {"holdout_episodes": len(holdout), "holdout_auc": auc,
               "both_classes_present": len(set(labels)) == 2, "qualified": qualified,
               "chronological_split": 0.8}
    model_id = uuid4().hex
    from database import get_conn
    with get_conn() as conn:
        conn.execute("UPDATE learning_ranker_models SET active=0")
        conn.execute("INSERT INTO learning_ranker_models VALUES (?,?,?,?,?,?,?)",
                     (model_id, datetime.now().astimezone().isoformat(), len(usable),
                      json.dumps(FEATURES), json.dumps(weights), json.dumps(metrics), int(qualified)))
        for item in usable:
            score = _sigmoid(sum(w*x for w, x in zip(weights, _vector(item))))
            conn.execute("INSERT OR REPLACE INTO learning_ranker_scores VALUES (?,?,?,?)",
                         (item["example_id"], model_id, score, datetime.now().astimezone().isoformat()))
    return {"status": "shadow_active" if qualified else "trained_not_qualified",
            "model_id": model_id, "usable_episodes": len(usable),
            "metrics": metrics, "order_authority": False}


def ranker_status(usable_count: int) -> dict:
    from database import get_conn
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM learning_ranker_models ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        return {"status": "collecting", "usable_episodes": usable_count, "required": MIN_EPISODES,
                "remaining": max(0, MIN_EPISODES-usable_count), "order_authority": False}
    return {"status": "shadow_active" if row["active"] else "trained_not_qualified",
            "model_id": row["model_id"], "usable_episodes": usable_count,
            "trained_episodes": row["episode_count"], "metrics": json.loads(row["metrics_json"]),
            "order_authority": False}
