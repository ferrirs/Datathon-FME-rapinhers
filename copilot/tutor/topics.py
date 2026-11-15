"""Topics: M3Kang has no topic field, so we derive one.

Three votes, added up:
1. Prototypes: each topic has a few English descriptions in mathematical terms.
   The problem goes to the topic whose description is nearest in the embeddings.
2. Keywords: a regular expression per topic, for the words that leave no doubt.
3. Seeds: the topics of the nearest problems that the team labelled by hand.

The margin between the best and the second topic says how sure we are. Problems
with a low margin are not used to measure mastery.
"""
import json
import os
import random
import re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
KEYWORD_VOTE = 0.08
SEED_VOTE = 0.04
SEED_NEIGHBOURS = 5


def load_topics():
    with open(os.path.join(HERE, "content", "topics.json"), encoding="utf-8") as f:
        topics = json.load(f)
    for topic in topics:
        topic["regex"] = re.compile(topic["keywords"], re.IGNORECASE)
    return topics


def load_cards():
    with open(os.path.join(HERE, "content", "cards_ca.json"), encoding="utf-8") as f:
        return json.load(f)


def load_analogies():
    """{topic name: analogy}. For the team's topics of data/temes.json, matched by their exact name:
    rename a topic there, and its analogy is simply not shown."""
    with open(os.path.join(HERE, "content", "analogies_ca.json"), encoding="utf-8") as f:
        return json.load(f)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def topic_scores(text, vec, topics, prototypes, seeds=()):
    """prototypes: {topic: [vector, ...]}; seeds: [(topic, vector), ...] labelled by hand."""
    scores = {}
    for topic in topics:
        key = topic["key"]
        scores[key] = max(dot(vec, p) for p in prototypes[key])
        if topic["regex"].search(text):
            scores[key] += KEYWORD_VOTE
    if seeds:
        nearest = sorted(seeds, key=lambda seed: -dot(vec, seed[1]))[:SEED_NEIGHBOURS]
        for key, votes in Counter(key for key, _vec in nearest).items():
            if key in scores:
                scores[key] += SEED_VOTE * votes
    return scores


def classify(text, vec, topics, prototypes, seeds=()):
    """Return (topic, margin over the second best)."""
    ranked = sorted(topic_scores(text, vec, topics, prototypes, seeds).items(), key=lambda kv: -kv[1])
    return ranked[0][0], ranked[0][1] - ranked[1][1]


def leave_one_out(labelled, topics, prototypes):
    """labelled: [(id, text, vec, topic)]. Each one is classified without its own label.

    Returns (hits, confusion), with confusion counting (true, predicted) pairs.
    """
    hits, confusion = 0, Counter()
    for pid, text, vec, truth in labelled:
        seeds = [(t, v) for other, _text, v, t in labelled if other != pid]
        predicted, _margin = classify(text, vec, topics, prototypes, seeds)
        hits += predicted == truth
        if predicted != truth:
            confusion[(truth, predicted)] += 1
    return hits, confusion


def kmeans(vectors, k, seed=42, rounds=15):
    """Plain k-means on unit vectors, to look at the data before fixing the topic list.

    Returns one cluster number per vector.
    """
    rng = random.Random(seed)
    centres = [list(v) for v in rng.sample(vectors, k)]
    assigned = [0] * len(vectors)
    for _ in range(rounds):
        changed = False
        for i, vec in enumerate(vectors):
            best = max(range(k), key=lambda c: dot(vec, centres[c]))
            changed |= best != assigned[i]
            assigned[i] = best
        if not changed:
            break
        for c in range(k):
            members = [vectors[i] for i in range(len(vectors)) if assigned[i] == c]
            if members:
                centres[c] = [sum(column) / len(members) for column in zip(*members)]
    return assigned
