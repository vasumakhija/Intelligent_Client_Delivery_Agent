import json
import logging
import pandas as pd
from datetime import datetime
from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function
from semantic_kernel.connectors.ai.ollama import OllamaChatCompletion
import chromadb

logging.basicConfig(
    filename="agent_logs.txt",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger(__name__)

from devops_fetcher import refresh_devops_data

kernel = Kernel()
kernel.add_service(
    OllamaChatCompletion(
        service_id="ollama",
        ai_model_id="llama3.2:latest",
        host="http://localhost:11434"
    )
)

# ── Connect to ChromaDB ────────────────────────────────────
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection    = chroma_client.get_or_create_collection("maq_projects")

# ══════════════════════════════════════════════════════════
# HEALTH SCORE ENGINE
# Calculates score 0-10 from real sprint metrics
# ══════════════════════════════════════════════════════════
def calculate_health(project_id: str) -> dict:
    """
    Pulls all passages for a project and calculates
    a health score based on completion, carryover,
    blocked items, bugs and velocity.
    Score 0-3  = Healthy (green)
    Score 4-6  = Watchlist (amber)
    Score 7-10 = At Risk (red)
    """
    passages = collection.get(
        where={"project_id": project_id},
        include=["documents", "metadatas"]
    )

    health = {
        "project_id":        project_id,
        "score":             0,
        "completion_pct":    0.0,
        "carryover_pct":     0.0,
        "blocked_count":     0,
        "bug_count":         0,
        "velocity":          100.0,
        "total_items":       0,
        "completed_items":   0,
        "key_reasons":       [],
        "planned_points":    0.0,
        "completed_points":  0.0,
    }

    for doc, meta in zip(passages["documents"], passages["metadatas"]):
        source = meta.get("source", "")

        # ── Extract from project summary passage ──
        if source == "project_summary":
            try:
                if "Total active work items:" in doc:
                    health["total_items"] = int(
                        doc.split("Total active work items:")[1].split(".")[0].strip()
                    )
                if "Planned story points:" in doc:
                    health["planned_points"] = float(
                        doc.split("Planned story points:")[1].split(".")[0].strip()
                    )
                if "Completed story points:" in doc:
                    health["completed_points"] = float(
                        doc.split("Completed story points:")[1].split(".")[0].strip()
                    )
                if "Completion percentage:" in doc:
                    health["completion_pct"] = float(
                        doc.split("Completion percentage:")[1].split("%")[0].strip()
                    )
                if "Carryover percentage:" in doc:
                    health["carryover_pct"] = float(
                        doc.split("Carryover percentage:")[1].split("%")[0].strip()
                    )
                if "Blocked items:" in doc:
                    health["blocked_count"] = int(
                        doc.split("Blocked items:")[1].split(".")[0].strip()
                    )
                if "Open bugs:" in doc:
                    health["bug_count"] = int(
                        doc.split("Open bugs:")[1].split(".")[0].strip()
                    )
            except Exception as e:
                print(f"  Parse error for {project_id}: {e}")
                pass

        # ── Count bugs from work items ──
        if source == "work_item":
            if "type: Bug" in doc and "State: Active" in doc:
                health["bug_count"] += 1
            if "State: Done" in doc or "State: Resolved" in doc:
                health["completed_items"] += 1

        # ── Count carryover from sprints ──
        if source == "sprint" and "past" in doc.lower():
            health["carryover_pct"] += 10  # each past sprint adds carryover signal

    # ── Calculate completion percentage ──
    planned = health["planned_points"]
    completed = health["completed_points"]



    # ── Calculate carryover percentage ──
    if health["total_items"] > 0:
        remaining = health["total_items"] - health["completed_items"]
        health["carryover_pct"] = round((remaining / health["total_items"]) * 100, 1)

    # ── Score calculation (0-10, higher = worse) ──
    score = 0
    reasons = []

    # Completion score (most important signal)
    comp = health["completion_pct"]
    if comp >= 80:
        score += 0
        reasons.append(f"good sprint completion ({comp}%)")
    elif comp >= 60:
        score += 2
        reasons.append(f"moderate sprint completion ({comp}%)")
    elif comp >= 40:
        score += 4
        reasons.append(f"low sprint completion ({comp}%)")
    else:
        score += 6
        reasons.append(f"very low sprint completion ({comp}%)")

    # Carryover score
    carryover = health["carryover_pct"]
    if carryover > 60:
        score += 2
        reasons.append(f"high carryover ({carryover}%)")
    elif carryover > 30:
        score += 1
        reasons.append(f"visible carryover ({carryover}%)")

    # Blocked items score
    blocked = health["blocked_count"]
    if blocked >= 4:
        score += 2
        reasons.append(f"many blocked work items ({blocked})")
    elif blocked >= 2:
        score += 1
        reasons.append(f"some blocked items ({blocked})")
    elif blocked == 1:
        score += 1
        reasons.append(f"1 blocked item")

    # Bug score
    bugs = health["bug_count"]
    if bugs >= 3:
        score += 1
        reasons.append(f"high bug load ({bugs} open bugs)")
    elif bugs >= 1:
        score += 0
        reasons.append(f"{bugs} open bug(s)")

    health["score"]       = min(score, 10)
    health["key_reasons"] = reasons

    # ── Health label ──
    if score <= 3:
        health["health_label"] = "Healthy"
        health["health_colour"] = "#28a745"
    elif score <= 6:
        health["health_label"] = "Watchlist"
        health["health_colour"] = "#ff9900"
    else:
        health["health_label"] = "At Risk"
        health["health_colour"] = "#dc3545"

    log.info(
        f"Health calculated for {project_id}: "
        f"{health['health_label']} (score {score}) — {', '.join(reasons)}"
    )
    return health

# ══════════════════════════════════════════════════════════
# HTML REPORT RENDERER
# ══════════════════════════════════════════════════════════
def render_html_report(query: str, projects_health: list) -> str:
    now = datetime.now().strftime("%d %B %Y, %H:%M")

    def health_badge(label, colour):
        return (
            f'<span style="background:{colour};color:#fff;padding:4px 14px;'
            f'border-radius:20px;font-size:13px;font-weight:600">{label}</span>'
        )

    rows = ""
    for p in projects_health:
        reasons_str = ", ".join(p["key_reasons"]) if p["key_reasons"] else "No issues detected"
        rows += f"""
        <tr>
            <td><strong>{p['project_id']}</strong></td>
            <td>{health_badge(p['health_label'], p['health_colour'])}</td>
            <td style="text-align:center;font-weight:600">{p['score']}</td>
            <td style="text-align:center">{p['completion_pct']}%</td>
            <td style="text-align:center">{p['carryover_pct']}%</td>
            <td style="text-align:center">{p['blocked_count']}</td>
            <td style="text-align:center">{p['bug_count']}</td>
            <td style="font-size:13px;color:#555">{reasons_str}</td>
        </tr>"""

    # KPI summary
    total    = len(projects_health)
    at_risk  = sum(1 for p in projects_health if p["health_label"] == "At Risk")
    watchlist = sum(1 for p in projects_health if p["health_label"] == "Watchlist")
    healthy  = sum(1 for p in projects_health if p["health_label"] == "Healthy")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>MAQ Software — Client Delivery Status Report</title>
<style>
  body  {{ font-family: Segoe UI, Arial, sans-serif; margin:0; padding:28px; background:#f4f6f9; color:#222; }}
  h1    {{ font-size:26px; font-weight:700; margin-bottom:4px; color:#1a1a2e; }}
  .sub  {{ color:#888; font-size:14px; margin-bottom:24px; }}
  .question {{ background:#fff; border-left:4px solid #1a1a2e; padding:12px 20px;
               border-radius:6px; margin-bottom:24px; font-size:15px; }}
  .question strong {{ color:#1a1a2e; }}
  .kpi-row {{ display:flex; gap:16px; margin-bottom:24px; }}
  .kpi  {{ background:#fff; border-radius:10px; padding:16px 24px; flex:1;
           box-shadow:0 1px 4px rgba(0,0,0,0.08); }}
  .kpi .num {{ font-size:36px; font-weight:700; }}
  .kpi .lbl {{ font-size:13px; color:#888; margin-top:4px; }}
  table {{ width:100%; border-collapse:collapse; background:#fff;
           border-radius:10px; overflow:hidden;
           box-shadow:0 1px 4px rgba(0,0,0,0.08); }}
  th    {{ background:#1a1a2e; color:#fff; padding:13px 16px;
           text-align:left; font-size:13px; font-weight:500; }}
  td    {{ padding:13px 16px; border-bottom:1px solid #f0f0f0; font-size:14px; }}
  tr:last-child td {{ border-bottom:none; }}
  tr:hover {{ background:#f8f9ff; }}
  .footer {{ margin-top:20px; font-size:12px; color:#aaa; }}
</style>
</head>
<body>
<h1>Client Delivery Status Report</h1>
<p class="sub">Generated from live Azure DevOps data &nbsp;|&nbsp; {now}</p>

<div class="question">
  <strong>Manager question:</strong> {query}
</div>

<div class="kpi-row">
  <div class="kpi">
    <div class="num">{total}</div>
    <div class="lbl">Total active projects</div>
  </div>
  <div class="kpi">
    <div class="num" style="color:#dc3545">{at_risk}</div>
    <div class="lbl">At risk</div>
  </div>
  <div class="kpi">
    <div class="num" style="color:#ff9900">{watchlist}</div>
    <div class="lbl">Watchlist</div>
  </div>
  <div class="kpi">
    <div class="num" style="color:#28a745">{healthy}</div>
    <div class="lbl">Healthy</div>
  </div>
</div>

<table>
  <thead>
    <tr>
      <th>Project</th>
      <th>Health</th>
      <th>Score</th>
      <th>Completion</th>
      <th>Carryover</th>
      <th>Blocked</th>
      <th>Bugs</th>
      <th>Key reasons</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>

<p class="footer">
  Data source: Azure DevOps REST API (live) &nbsp;·&nbsp;
  Context: Local project documentation (RAG) &nbsp;·&nbsp;
  Generated by Agent 3 — Semantic Kernel Orchestrator | MAQ Software Capstone
</p>
</body>
</html>"""

    with open("report_output.html", "w") as f:
        f.write(html)

    log.info("HTML report saved to report_output.html")
    return "report_output.html"

# ══════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════
async def run_orchestrator(query: str):
    log.info(f"Orchestrator started. Query: {query}")
    print(f"\nOrchestrator running for: '{query}'")
    print("="*55)

    # Refresh live DevOps data first
    refresh_devops_data(collection)

    projects = ["Alpha", "Beta", "Gamma"]
    projects_health = []

    for project_id in projects:
        print(f"  Calculating health for {project_id}...")
        health = calculate_health(project_id)
        projects_health.append(health)
        print(
            f"  {project_id}: {health['health_label']} "
            f"(score {health['score']}, "
            f"completion {health['completion_pct']}%, "
            f"blocked {health['blocked_count']})"
        )

    output_file = render_html_report(query, projects_health)
    print(f"\nReport saved to: {output_file}")
    print("Open report_output.html in your browser!")
    log.info("Orchestrator completed successfully")
    return output_file


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_orchestrator(
        "Which active projects are currently classified as At Risk?"
    ))