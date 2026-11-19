"""Static NIST CSF and incident-response mappings for TwinGuard risk signals."""

from __future__ import annotations

from .models import CsfMapping, IncidentAction

CSF_MAPPINGS: dict[str, list[CsfMapping]] = {
    "velocity_spoof": [
        CsfMapping(
            function="Identify",
            category="ID.AM",
            subcategory="ID.AM-01",
            rationale=(
                "The follower robot and its V2V communication channel are assets that must be "
                "inventoried and their data flows understood before injection can be detected reliably."
            ),
        ),
        CsfMapping(
            function="Identify",
            category="ID.RA",
            subcategory="ID.RA-01",
            rationale=(
                "A velocity-spoof attack represents an identified threat event against the "
                "V2V command channel. The threat can appear as a zeroed, underreported, overreported, "
                "fixed, or ramped leader-speed signal, with different operational effects on follower behavior."
            ),
        ),
        CsfMapping(
            function="Detect",
            category="DE.CM",
            subcategory="DE.CM-01",
            rationale=(
                "Continuous monitoring of leader_input_v against actual leader velocity is the "
                "primary detection control for injection attacks on the V2V channel."
            ),
        ),
        CsfMapping(
            function="Detect",
            category="DE.AE",
            subcategory="DE.AE-02",
            rationale=(
                "A divergence between the leader velocity broadcast over the V2V channel and the "
                "leader's physical velocity constitutes an adverse event requiring analysis and triage."
            ),
        ),
        CsfMapping(
            function="Respond",
            category="RS.AN",
            subcategory="RS.AN-03",
            rationale=(
                "Detected spoofing events require incident analysis: determining affected robots, "
                "the spoof window, the observed spoof subtype, the velocity delta, and whether the event was controlled or unexpected."
            ),
        ),
        CsfMapping(
            function="Respond",
            category="RS.CO",
            subcategory="RS.CO-02",
            rationale=(
                "Findings must be communicated to experiment operators and documented for "
                "post-session review and threshold calibration."
            ),
        ),
    ],
    "timing_gap": [
        CsfMapping(
            function="Identify",
            category="ID.RA",
            subcategory="ID.RA-01",
            rationale=(
                "Frame timing gaps indicate a potential availability risk to the digital twin data stream. "
                "Gaps during active platooning may mask concurrent attack signals and degrade risk assessment."
            ),
        ),
        CsfMapping(
            function="Detect",
            category="DE.CM",
            subcategory="DE.CM-03",
            rationale=(
                "Frame delivery rate should be continuously monitored. Gaps exceeding expected "
                "intervals (> 1.0 s) indicate a monitoring or availability gap that requires investigation."
            ),
        ),
        CsfMapping(
            function="Protect",
            category="PR.DS",
            subcategory="PR.DS-01",
            rationale=(
                "Data availability controls should ensure continuous frame delivery from the simulation environment."
            ),
        ),
    ],
    "recording_overflow": [
        CsfMapping(
            function="Identify",
            category="ID.RA",
            subcategory="ID.RA-01",
            rationale=(
                "Recording overflow reduces evidence completeness, limiting the fidelity of risk "
                "assessment for this session. It is itself a risk to the assessment process."
            ),
        ),
        CsfMapping(
            function="Protect",
            category="PR.DS",
            subcategory="PR.DS-11",
            rationale=(
                "Data integrity and retention controls must prevent loss of recorded session frames. "
                "Buffer limits should be tuned before safety-critical experiment runs."
            ),
        ),
    ],
}

IR_ACTIONS: dict[str, list[IncidentAction]] = {
    "velocity_spoof": [
        IncidentAction(
            phase="Detection and Analysis",
            action=(
                "Treat the detection as a potential unsafe control-command compromise. Notify the "
                "operator or safety supervisor, verify the physical state of affected robots, and "
                "confirm whether any robot is still moving under the suspect leader signal."
            ),
            rationale=(
                "For a physical system, immediate human awareness and state confirmation are needed "
                "before deeper analysis because the incident may create real safety impact."
            ),
        ),
        IncidentAction(
            phase="Detection and Analysis",
            action=(
                "For each affected robot, compare the received leader_input_v command with the "
                "leader's measured velocity and robot motion telemetry to confirm scope, subtype, magnitude, timing, and impact."
            ),
            rationale=(
                "A physical incident assessment must connect the cyber signal anomaly to actual robot behavior."
            ),
        ),
        IncidentAction(
            phase="Containment Eradication and Recovery",
            action=(
                "Place affected robots into a safe state using the approved safety procedure, such as "
                "controlled stop, manual override, safe mode, or emergency stop when motion risk is immediate."
            ),
            rationale=(
                "Containment for cyber-physical systems starts by reducing physical harm, even if "
                "that temporarily interrupts availability."
            ),
        ),
        IncidentAction(
            phase="Containment Eradication and Recovery",
            action=(
                "Isolate the affected command channel by disabling untrusted publishers, blocking "
                "suspect broker clients, rotating credentials, and enforcing topic write ACLs."
            ),
            rationale=(
                "The suspected injection path must be contained before robots are allowed to resume "
                "autonomous operation."
            ),
        ),
        IncidentAction(
            phase="Post-Incident Activity",
            action=(
                "Document the full physical and cyber timeline: first detection, affected robots, "
                "operator actions, robot state changes, command deltas, containment steps, and recovery decision."
            ),
            rationale=(
                "Post-incident records for physical systems must support safety review, root-cause analysis, and hardening."
            ),
        ),
    ],
    "timing_gap": [
        IncidentAction(
            phase="Detection and Analysis",
            action=(
                "Identify the precise frame range and timestamp of the gap; determine whether it "
                "coincides with an active attack window or robot state transition."
            ),
            rationale=(
                "Correlating timing gaps with attack periods establishes whether the gap is causal or coincidental."
            ),
        ),
    ],
    "recording_overflow": [
        IncidentAction(
            phase="Detection and Analysis",
            action=(
                "Note that recording overflow limits evidence completeness; all findings derived "
                "from this session carry reduced confidence and should be treated as lower bounds."
            ),
            rationale=(
                "Evidence limitations constrain assessment fidelity and must be captured in the incident record."
            ),
        ),
    ],
}
