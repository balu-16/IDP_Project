"""Frozen transfer protocol, complete source snapshots, and strict provenance."""
from dataclasses import asdict
from pathlib import Path

from research.accuracy_v2.core import Config as BaselineConfig, SEEDS
from research.accuracy_v2.pipeline import model_identity
from research.accuracy_v2.storage import (ROOT, atomic_bytes, environment_identity,
    read_checked, write_checked, sha, digest, utc)
from research.accuracy_v3.core import Config as RefinementConfig
from research.accuracy_v3.pipeline import expected_methods
from research.accuracy_v3.storage import Store as V3Store, extension_identity
from research.selection import GASConfig
from . import VERSION, data

STUDY = ROOT / "research/runs/fourth_dataset_v1_trec_covid"
CACHE = ROOT / "research/cache/fourth_dataset_v1/trec-covid"


def sources():
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))}


def controls():
    keys = ("mmr_weight", "old_mmr_weight", "old_config", "legacy_threshold")
    records, origins = [], {}
    for name in ("scifact", "nfcorpus", "fiqa"):
        path = ROOT / f"research/runs/accuracy_v2_{name}_dev/frozen.json"
        saved = read_checked(path)
        records.append({key: saved[key] for key in keys})
        origins[str(path.relative_to(ROOT))] = sha(path)
    if not all(r == records[0] for r in records):
        raise ValueError("Prior development-frozen control profiles disagree")
    expected = {"mmr_weight": 0., "old_mmr_weight": 0., "legacy_threshold": .7,
                "old_config": asdict(GASConfig(diversity_weight=.1, coefficient_bits=6))}
    if records[0] != expected:
        raise ValueError("Common controls differ from the predeclared transfer settings")
    return {**expected, "config": asdict(BaselineConfig())}, origins


def code_identity():
    return {"environment": environment_identity(), "extension": extension_identity(), "fourth_sources": sources()}


def freeze(study=STUDY):
    study = Path(study)
    if (study / "frozen.json").exists():
        require_frozen(study)
        return study / "frozen.json"
    preflight = read_checked(study / "preflight.json")
    smoke = read_checked(study / "smoke.json")
    code = code_identity()
    for name, record in (("preflight", preflight), ("smoke", smoke)):
        if not record["passed"] or record["code"] != code:
            raise ValueError(f"{name} missing, failed, or belongs to different code")
    inv = data.inventory()
    if preflight["data"] != inv or preflight["models"] != model_identity(True):
        raise ValueError("Preflight data/model fingerprints no longer match")
    baseline, origins = controls()
    roster = expected_methods()
    if len(roster) != 27:
        raise ValueError("Expected all 27 comparisons")
    identity = {"schema": VERSION, "dataset": "trec-covid", "kind": "transfer-test",
        **code, "data": inv, "models": preflight["models"], "base_frozen": baseline,
        "control_origins": origins, "config": asdict(RefinementConfig()),
        "query_ids": inv["query_ids"], "methods": roster, "seeds": list(SEEDS),
        "full_controls": True, "legacy_grover": True,
        "inventory_sha256": data.save_ids(study / "dataset_inventory.json"),
        "preflight_sha256": sha(study / "preflight.json"), "smoke_sha256": sha(study / "smoke.json"),
        "cache_namespace": str(CACHE.relative_to(ROOT)),
        "tuning": "None; predeclared transfer configuration, no test-judgment tuning or confirmation",
        "gate": {"ndcg5_tolerance": 1e-12, "recall_retention": .98, "redundancy_strict_decrease": True,
                 "evaluation_after_all_queries": 50},
        "statistical_family": {"baselines": ["gas_l6", "l6_only", "greedy_v3", "exact_float_v3", "random_v3", "l6_union", "gas", "mmr_l6", "neural_l6_top64"],
            "metrics": ["nDCG@5", "Recall@8", "nDCG@8", "redundancy"],
            "bootstrap_resamples": 10000, "randomization_resamples": 10000, "tie_tolerance": 1e-12},
        "diagnostics": ["Precision@8", "judged@8", "unjudged@8", "nonrelevant_judged@8", "per-query recall losses"],
        "limitations": "Larger classical corpus coverage; fixed small selection pool; compact classical simulation; no quantum corpus-search scaling or Grover advantage established. Earlier FiQA failure is preserved."}
    paths = {**code["environment"]["sources"], **code["extension"]["sources"], **code["fourth_sources"]}
    for relative, expected in paths.items():
        target = study / "source_snapshot" / relative
        atomic_bytes(target, (ROOT / relative).read_bytes())
        if sha(target) != expected:
            raise ValueError(f"Source changed while freezing: {relative}")
    write_checked(study / "frozen.json", {"created_utc": utc(), "identity": identity})
    return study / "frozen.json"


def require_frozen(study=STUDY):
    study = Path(study)
    ident = read_checked(study / "frozen.json")["identity"]
    current = code_identity()
    for key, value in current.items():
        if ident[key] != value:
            raise ValueError(f"Incompatible frozen protocol: {key} changed; restore recorded sources/dependencies")
    if ident["data"] != data.inventory():
        raise ValueError("Incompatible frozen protocol: dataset/archive changed")
    if ident["models"] != model_identity(True):
        raise ValueError("Incompatible frozen protocol: pinned model contents changed")
    if controls() != (ident["base_frozen"], ident["control_origins"]):
        raise ValueError("Incompatible frozen protocol: common controls changed")
    for name in ("inventory", "preflight", "smoke"):
        filename = "dataset_inventory.json" if name == "inventory" else f"{name}.json"
        if sha(study / filename) != ident[f"{name}_sha256"]:
            raise ValueError(f"Frozen {name} artifact changed")
    preflight = read_checked(study / "preflight.json")
    if sha(ROOT / "build/tools/trec_eval") != preflight["trec_eval_sha256"]:
        raise ValueError("Independent trec_eval executable changed since preflight")
    smoke = read_checked(study / "smoke.json")
    if sha(study / "smoke_tests.log") != smoke["test_log_sha256"]:
        raise ValueError("Frozen smoke-test evidence changed")
    for relative, expected in {**ident["environment"]["sources"], **ident["extension"]["sources"], **ident["fourth_sources"]}.items():
        if sha(study / "source_snapshot" / relative) != expected:
            raise ValueError(f"Frozen source snapshot corrupt: {relative}")
    return ident


class Store(V3Store):
    def __init__(self, directory, identity, resume=False):
        if identity["fourth_sources"] != sources():
            raise ValueError("Fourth-dataset source fingerprint mismatch")
        super().__init__(directory, identity, resume)
        for relative, expected in identity["fourth_sources"].items():
            path = self.path / "source_snapshot" / relative
            if not resume:
                atomic_bytes(path, (ROOT / relative).read_bytes())
            if not path.is_file() or sha(path) != expected:
                raise ValueError(f"Fourth-dataset snapshot corrupt: {relative}")

    def verify_feature_stages(self, query_ids):
        expected = set(map(str, query_ids))
        for stage in ("retrieved", "original_features"):
            found = set()
            for path in (self.path / stage).glob("*.json"):
                record = read_checked(path)
                qid = record["qid"]
                if path != self.file(stage, qid) or qid in found:
                    raise ValueError(f"Duplicate or misnamed {stage} artifact")
                self.get(stage, qid)
                found.add(qid)
            if found != expected:
                raise ValueError(f"Incomplete {stage} artifact coverage")

    def seal(self, query_ids, validate):
        if self.identity["fourth_sources"] != sources():
            raise ValueError("Fourth-dataset sources changed during execution")
        self.verify_feature_stages(query_ids)
        super().seal(query_ids, validate)

    def verify(self):
        if self.identity["fourth_sources"] != sources():
            raise ValueError("Fourth-dataset sources changed since collection")
        manifest = super().verify()
        self.verify_feature_stages(manifest["query_ids"])
        return manifest
