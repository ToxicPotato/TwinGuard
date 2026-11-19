"""NIST SP 800-30 aligned risk object data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CsfMapping:
    """One NIST CSF 2.0 function / category / subcategory mapping."""

    function: str
    category: str
    subcategory: str
    rationale: str

    def to_dict(self) -> dict:
        return {
            "function": self.function,
            "category": self.category,
            "subcategory": self.subcategory,
            "rationale": self.rationale,
        }


@dataclass
class IncidentAction:
    """One NIST SP 800-61 Rev. 3 incident handling recommendation."""

    phase: str
    action: str
    rationale: str

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "action": self.action,
            "rationale": self.rationale,
        }


@dataclass
class RiskObject:
    """One NIST-aligned risk finding derived from a recorded live run."""

    id: str
    source_type: str
    run_id: str
    frame_range: tuple[int, int] | None
    timestamp_range: tuple[float, float] | None
    affected_robots: list[str]
    signal_type: str
    signal_subtype: str | None
    observed_signal_subtypes: list[str]
    evidence_summary: str
    likelihood: int
    impact: int
    risk_score: int
    risk_level: str
    assumptions: list[str]
    confidence: float
    completeness: float
    csf_mappings: list[CsfMapping]
    incident_actions: list[IncidentAction]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "run_id": self.run_id,
            "frame_range": list(self.frame_range) if self.frame_range else None,
            "timestamp_range": list(self.timestamp_range) if self.timestamp_range else None,
            "affected_robots": self.affected_robots,
            "signal_type": self.signal_type,
            "signal_subtype": self.signal_subtype,
            "observed_signal_subtypes": self.observed_signal_subtypes,
            "evidence_summary": self.evidence_summary,
            "likelihood": self.likelihood,
            "impact": self.impact,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "assumptions": self.assumptions,
            "confidence": round(self.confidence, 3),
            "completeness": round(self.completeness, 3),
            "csf_mappings": [mapping.to_dict() for mapping in self.csf_mappings],
            "incident_actions": [action.to_dict() for action in self.incident_actions],
        }


def risk_level_from_score(score: int) -> str:
    if score >= 17:
        return "critical"
    if score >= 10:
        return "high"
    if score >= 5:
        return "moderate"
    return "low"


def build_risk_matrix(risk_objects: list[dict]) -> dict:
    """Build a 5x5 likelihood/impact matrix from serialized risk objects."""
    grid: list[list[list[str]]] = [[[] for _ in range(5)] for _ in range(5)]
    for obj in risk_objects:
        likelihood_idx = max(0, min(4, int(obj["likelihood"]) - 1))
        impact_idx = max(0, min(4, int(obj["impact"]) - 1))
        grid[likelihood_idx][impact_idx].append(obj["id"])

    counts: dict[str, int] = {"low": 0, "moderate": 0, "high": 0, "critical": 0}
    for obj in risk_objects:
        level = obj.get("risk_level", "low")
        if level in counts:
            counts[level] += 1

    return {
        "grid": grid,
        "impact_labels": ["Very Low", "Low", "Moderate", "High", "Very High"],
        "likelihood_labels": ["Very Low", "Low", "Moderate", "High", "Very High"],
        "counts": counts,
        "total": len(risk_objects),
    }
