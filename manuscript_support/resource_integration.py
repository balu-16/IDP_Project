"""Read-only import of a sealed resource study into manuscript evidence."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_resource(mapping):
    relative = mapping.get("resource_study")
    if relative is None:
        return None
    from research.resource_study_v1.storage import protocol, read_checked, sha
    directory = ROOT / relative
    p = protocol(directory)
    manifest = read_checked(directory / "manifest.json")
    reports = read_checked(directory / "report_manifest.json")
    if (manifest["protocol_sha256"] != sha(directory / "protocol.json")
            or reports["study_manifest_sha256"] != sha(directory / "manifest.json")):
        raise ValueError("Resource report is not bound to the sealed study")
    actual = {str(path.relative_to(directory)) for path in (directory / "results").glob("*.json")}
    if actual != set(manifest["files"]):
        raise ValueError("Resource artifact coverage changed")
    for relative_file, expected in manifest["files"].items():
        if sha(directory / relative_file) != expected:
            raise ValueError("Resource result checksum mismatch")
    for name, expected in reports["files"].items():
        if sha(directory / name) != expected:
            raise ValueError("Resource summary/table checksum mismatch")
    summary = read_checked(directory / "summary.json")
    if summary["manifest_sha256"] != sha(directory / "manifest.json"):
        raise ValueError("Resource summary identity mismatch")
    condition = p["prerequisites"]
    fiqa = ROOT / condition["fiqa_directory"]
    if (sha(fiqa / "manifest.json") != condition["fiqa_manifest_sha256"]
            or sha(fiqa / "evaluation.json") != condition["fiqa_evaluation_sha256"]):
        raise ValueError("FiQA follow-up provenance changed")
    return {"directory": str(directory.relative_to(ROOT)), "summary": summary,
        "protocol": p, "manifest_sha256": sha(directory / "manifest.json"),
        "report_manifest_sha256": sha(directory / "report_manifest.json"),
        "hardware_record": json.loads((ROOT / "manuscript_support/records/resource_hardware.json").read_text()),
        "hardware_sha256": sha(ROOT / "manuscript_support/records/resource_hardware.json"),
        "resource_table": (directory / "resource_table.tex").read_text()}


def findings(resource):
    summary = resource["summary"]
    native = [cell for values in summary["native"].values() for cell in values.values()]
    measured = sum(cell["completed"] for cell in native)
    limited = sum(cell["limited"] for cell in native)
    validated = sum(cell["native_simulations_completed"] for cell in native)
    memory = sum(cell["native_simulations_resource_limited"] for cell in native)
    return (
        f"The separate resource study freezes 32 training-confirmation queries per collection and five seeds. "
        r"It varies eligible tail pools \(M\in\{3,5,8,12,16,20\}\) and pair precision "
        r"\(b\in\{4,8,12,16\}\), retaining the baseline tail. "
        f"All {measured} completed native cells use at most two fixed seed-zero queries per available dataset/pool; "
        r"unavailable sampled seed-zero sizes use explicitly artificial stress cases. "
        f"Native simulation validated {validated} complete iterations; {memory} simulation attempts met the "
        f"memory guard, and {limited} whole circuit tasks met resource limits. "
        "Separate two-bit toy tests verify nontrivial five-decision marking and reflection. "
        r"Full-iteration synthesis is restricted to \(M\leq8\), and native simulation to \(M\leq5\). "
        "All limits and complete precision results remain in the companion records."
    )


def fiqa_followup(resource, earlier_headline=True):
    gate = resource["protocol"]["prerequisites"]["fiqa_gate"]
    return (
        r"The additional 648-query FiQA refinement follow-up preserved nDCG@5 and reduced redundancy by "
        f"{gate['redundancy_relative_reduction_percent']:.2f}" + r"\%, but Recall@8 fell "
        f"{-gate['recall_relative_change_percent']:.2f}" + r"\% relative, exceeding the 2\% allowance. "
        "It failed the frozen gate without retuning. " +
        ("The headline retains the disclosed earlier FiQA configuration." if earlier_headline else
         "This historical failure is recorded separately from the reported configuration.")
    )
