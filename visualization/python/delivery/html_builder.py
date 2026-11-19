"""
html_builder.py - Generate a self-contained HTML report from enriched twin data.

Produces a single .html file with Plotly charts embedded inline.
No backend, no internet connection required to open the report.
"""

import html as _html
import math
import os
from datetime import datetime, timezone

STATE_LABELS = {0: "AUTONOMOUS", 1: "CANDIDATE", 2: "ALIGNING", 3: "PLATOONING", 4: "RECOVERY"}
ROBOT_COLORS = ["#4fc3f7", "#ff8a65", "#81c784", "#ce93d8", "#fff176"]


# ── Data helpers ──────────────────────────────────────────────────────────────

def _series(frames: list[dict], robot_id: str, field: str) -> list:
    """Extract one signal time series for a robot. None where missing (Plotly renders as gap)."""
    return [f["robots"].get(robot_id, {}).get(field) for f in frames]


def _velocity_spoof_indices(frames: list[dict], robot_id: str) -> list[int]:
    """Return frame indices where velocity_spoof is flagged for a robot."""
    return [
        i for i, f in enumerate(frames)
        if f.get("scenario", {}).get("per_robot", {}).get(robot_id, {}).get("velocity_spoof", False)
    ]


# ── Chart builder ─────────────────────────────────────────────────────────────

def _build_figure(run_name: str, run: dict):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    frames = run["frames"]
    robots = run["meta"]["robots"]
    t = [f["t"] for f in frames]
    colors = {rid: ROBOT_COLORS[i % len(ROBOT_COLORS)] for i, rid in enumerate(robots)}

    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        subplot_titles=["State", "Velocity (m/s)", "Gap Distance (m)", "Lateral Error (m)", "Wheel Speeds (rad/s)"],
        vertical_spacing=0.06,
    )

    for rid in robots:
        c = colors[rid]

        # State — step chart so transitions are crisp
        fig.add_trace(go.Scatter(
            x=t, y=_series(frames, rid, "st"),
            name=rid, line=dict(color=c, shape="hv"),
            legendgroup=rid, showlegend=True,
        ), row=1, col=1)

        # Velocity
        v = _series(frames, rid, "v")
        fig.add_trace(go.Scatter(
            x=t, y=v, name=f"{rid} v",
            line=dict(color=c), legendgroup=rid, showlegend=False,
        ), row=2, col=1)

        spoof_idx = _velocity_spoof_indices(frames, rid)
        if spoof_idx:
            fig.add_trace(go.Scatter(
                x=[t[i] for i in spoof_idx],
                y=[v[i] for i in spoof_idx],
                mode="markers",
                name=f"{rid} VEL SPOOF",
                marker=dict(color="red", size=9, symbol="x-thin", line=dict(width=2, color="red")),
                legendgroup=f"{rid}_spoof",
                showlegend=True,
            ), row=2, col=1)

        # Gap distance (distance sensor — followers only, leader has dv=False)
        fig.add_trace(go.Scatter(
            x=t, y=_series(frames, rid, "d"),
            name=f"{rid} gap", line=dict(color=c),
            legendgroup=rid, showlegend=False,
        ), row=3, col=1)

        # Lateral error (routed — controller input)
        fig.add_trace(go.Scatter(
            x=t, y=_series(frames, rid, "le"),
            name=f"{rid} le", line=dict(color=c),
            legendgroup=rid, showlegend=False,
        ), row=4, col=1)

        # Wheel speeds — solid = left, dashed = right
        fig.add_trace(go.Scatter(
            x=t, y=_series(frames, rid, "wl"),
            name=f"{rid} wl", line=dict(color=c, dash="solid"),
            legendgroup=rid, showlegend=False,
        ), row=5, col=1)
        fig.add_trace(go.Scatter(
            x=t, y=_series(frames, rid, "wr"),
            name=f"{rid} wr", line=dict(color=c, dash="dash"),
            legendgroup=rid, showlegend=False,
        ), row=5, col=1)

    fig.update_yaxes(
        tickvals=list(STATE_LABELS.keys()),
        ticktext=[f"{k} {v}" for k, v in STATE_LABELS.items()],
        row=1, col=1,
    )
    fig.update_xaxes(title_text="Time (s)", row=5, col=1)
    fig.update_layout(
        height=1000,
        title_text=f"Run: {run_name}",
        template="plotly_dark",
        paper_bgcolor="#16213e",
        plot_bgcolor="#0f3460",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    return fig


# ── Summary table ─────────────────────────────────────────────────────────────

def _summary_table(run_name: str, run: dict) -> str:
    meta = run["meta"]
    frames = run["frames"]
    robots = meta["robots"]
    load = meta.get("comparison", {}).get("load", {})

    spoof_counts = {
        rid: sum(
            1 for f in frames
            if f.get("scenario", {}).get("per_robot", {}).get(rid, {}).get("velocity_spoof", False)
        )
        for rid in robots
    }

    _meta_duration = meta.get("duration")
    duration = (
        _meta_duration
        if isinstance(_meta_duration, (int, float)) and math.isfinite(_meta_duration)
        else (frames[-1]["t"] - frames[0]["t"] if len(frames) > 1 else 0)
    )
    frame_count = meta.get("count", len(frames))
    safe_name = _html.escape(run_name)
    safe_robots = ", ".join(_html.escape(r) for r in robots)

    rows = [
        f"<tr><td>Duration</td><td>{duration:.1f} s</td></tr>",
        f"<tr><td>Frames</td><td>{frame_count}</td></tr>",
        f"<tr><td>Robots</td><td>{safe_robots}</td></tr>",
    ]
    if load:
        rows += [
            f"<tr><td>LowRes avg</td><td>{load.get('low_res_avg_ms', 0):.3f} ms</td></tr>",
            f"<tr><td>HighRes avg</td><td>{load.get('high_res_avg_ms', 0):.3f} ms</td></tr>",
            f"<tr><td>Scenario avg</td><td>{load.get('scenario_avg_ms', 0):.3f} ms</td></tr>",
        ]
    for rid, count in spoof_counts.items():
        flag = " ⚠" if count > 0 else ""
        rows.append(f"<tr><td>Velocity spoof ({_html.escape(rid)})</td><td>{count} frames{flag}</td></tr>")

    return f"""
    <div class="summary">
      <h2>{safe_name}</h2>
      <table>{''.join(rows)}</table>
    </div>"""


# ── HTML assembly ─────────────────────────────────────────────────────────────

def _assemble_html(runs: dict) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections = []

    for i, (run_name, run) in enumerate(runs.items()):
        summary = _summary_table(run_name, run)
        fig = _build_figure(run_name, run)
        # Inline Plotly JS only on the first figure — subsequent figures reuse it
        chart = fig.to_html(
            full_html=False,
            include_plotlyjs=(i == 0),
            config={"responsive": True},
        )
        sections.append(f"<section>{summary}{chart}</section>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TwinGuard Report</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #16213e; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; padding: 24px; }}
    h1 {{ font-size: 1.6rem; margin-bottom: 8px; color: #4fc3f7; letter-spacing: 0.1em; }}
    h2 {{ font-size: 1.1rem; margin-bottom: 12px; color: #90caf9; }}
    section {{ margin-bottom: 56px; border-top: 1px solid #1e3a5f; padding-top: 24px; }}
    .summary {{ margin-bottom: 16px; }}
    table {{ border-collapse: collapse; font-size: 0.85rem; }}
    td {{ padding: 3px 20px 3px 0; }}
    td:first-child {{ color: #78909c; min-width: 180px; }}
    .meta {{ font-size: 0.75rem; color: #546e7a; margin-bottom: 32px; }}
  </style>
</head>
<body>
  <h1>TwinGuard Report</h1>
  <p class="meta">Generated {generated}</p>
  {"".join(sections)}
</body>
</html>"""


# ── Public API ────────────────────────────────────────────────────────────────

def build_html(runs: dict, out_path: str = None) -> str:
    """Build and write the self-contained HTML report. Returns the output path."""
    html = _assemble_html(runs)

    if out_path is None:
        out_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "output",
        )
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "report.html")

    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(html)

    size_kb = os.path.getsize(out_path) // 1024
    print(f"  Report saved: {out_path}  ({size_kb} KB)")
    return out_path
