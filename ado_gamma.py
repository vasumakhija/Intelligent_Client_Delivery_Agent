import os, sys, json, time, base64, argparse
import urllib.request, urllib.error, urllib.parse
import os
from dotenv import load_dotenv

load_dotenv()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Configuration — update these or pass via CLI / environment variables
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
ORG     = os.environ.get("AZURE_DEVOPS_ORG",     "Your Organization")
PROJECT = os.environ.get("AZURE_DEVOPS_PROJECT",  "Gamma")
PAT = os.getenv("AZURE_DEVOPS_PAT")

SEP    = "=" * 70
SUBSEP = "-" * 70
 
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Project-specific data — Gamma (P003)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
PROJECT_ID   = "P003"
PROJECT_NAME = "Gamma"
AREA_NAME    = "Gamma"
 
# Sprints: sprint_id -> {name, start, end, status}
SPRINTS = {
    "S1": {"name": "Gamma Sprint 1", "start": "2026-03-01", "end": "2026-03-14", "status": "Completed"},
    "S2": {"name": "Gamma Sprint 2", "start": "2026-03-15", "end": "2026-03-28", "status": "In Progress"},
}
 
# Work Items: (sprint_id, type, title, state, story_points, priority, assigned_to, blocked)
WORK_ITEMS = [
    ("S1", "Issue", "Create leadership KPI dashboard", "Active", 8, 1, "Grace", True),
    ("S1", "Issue", "Build pipeline status visual", "Closed", 5, 2, "Henry", False),
    ("S1", "Task", "Prepare executive data model", "Active", 8, 1, "Irene", True),
    ("S1", "Issue", "[Bug] Fix broken KPI mapping", "Active", 3, 1, "Grace", True),
    ("S2", "Issue", "Create board-ready summary page", "New", 8, 1, "Henry", False),
    ("S2", "Task", "Implement role-based filters", "Active", 5, 2, "Irene", True),
    ("S2", "Task", "Tune semantic model performance", "Active", 5, 1, "Grace", False),
    ("S2", "Issue", "[Bug] Fix executive drilldown bug", "Active", 3, 1, "Henry", False),
    ("S2", "Issue", "[Bug] Resolve refresh failure bug", "New", 3, 1, "Irene", False),
]
 
# Milestones: (name, due_date, status, delay_days, owner, notes)
MILESTONES = [
    ("Requirements Signoff", "2026-03-12", "Completed", 1, "vasu", "Signoff received after escalation"),
    ("Executive Review", "2026-03-23", "Delayed", 8, "vasu", "KPI definitions still unstable"),
    ("UAT Start", "2026-04-03", "Delayed", 10, "vasu", "Blocked by unresolved dashboard dependencies"),
]
 
# Risks: (title, severity, status, mitigation, owner)
RISKS = [
    ("Executive KPI definitions not finalized", "High", "Open", "Escalate in steering review and lock KPI scope", "vasu"),
    ("Multiple blocked work items impacting delivery", "High", "Open", "Resolve upstream dependencies and rebalance sprint load", "vasu"),
]
 
# Project metadata from projects.csv
PROJECT_INFO = {
    "project_id":          "P003",
    "project_name":        "Gamma",
    "client_name":         "Northwind",
    "delivery_type":       "Power BI",
    "project_manager":     "vasu",
    "start_date":          "2026-03-03",
    "target_end_date":     "2026-05-20",
    "current_status":      "Active",
    "priority":            "High",
    "planned_total_hours": 340,
}
 
 
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HTTP helpers — pure stdlib
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
def _auth(pat):
    return {"Authorization": "Basic " + base64.b64encode((":" + pat).encode()).decode()}
 
def _get(url, pat):
    req = urllib.request.Request(url, headers=_auth(pat))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode(errors="replace")}
    except Exception as e:
        return 0, {"error": str(e)}
 
def _patch(url, body, pat):
    data    = json.dumps(body).encode("utf-8")
    headers = dict(_auth(pat))
    headers["Content-Type"] = "application/json-patch+json"
    req = urllib.request.Request(url, data=data, headers=headers, method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode(errors="replace")}
    except Exception as e:
        return 0, {"error": str(e)}
 
def _post(url, body, pat):
    data    = json.dumps(body).encode("utf-8")
    headers = dict(_auth(pat))
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode(errors="replace")}
    except Exception as e:
        return 0, {"error": str(e)}
 
def _delete(url, pat):
    req = urllib.request.Request(url, headers=_auth(pat), method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except Exception:
        return 0
 
 
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# URL builders
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
def _base_url():
    return "https://dev.azure.com/" + ORG + "/" + PROJECT
 
def _wi_create_url(wi_type):
    t = urllib.parse.quote(wi_type, safe="")
    return _base_url() + "/_apis/wit/workitems/$" + t + "?api-version=7.0"
 
def _wi_update_url(item_id):
    return _base_url() + "/_apis/wit/workitems/" + str(item_id) + "?api-version=7.0"
 
 
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Connection & write checks
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
def check_connection(pat):
    url = "https://dev.azure.com/" + ORG + "/_apis/projects?api-version=7.0"
    status, data = _get(url, pat)
    if status == 401:
        print("  FAIL 401 — PAT invalid or expired"); return False
    if status != 200:
        print("  FAIL " + str(status)); return False
    projects = [p["name"] for p in data.get("value", [])]
    print("  Connected: " + ORG + "  |  Projects: " + str(projects))
    if PROJECT not in projects:
        print("  ERROR: project '" + PROJECT + "' not found"); return False
    print("  Project confirmed: " + PROJECT)
    return True
 
def check_write(pat):
    print("Checking write permission...")
    url  = _wi_create_url("Task")
    body = [{"op": "add", "path": "/fields/System.Title", "value": "[PROBE] delete me"}]
    status, data = _patch(url, body, pat)
    if status == 401:
        print("  FAIL 401 — PAT needs Write scope"); return False
    if status in (200, 201):
        probe_id = data.get("id")
        print("  Write OK (probe #" + str(probe_id) + ")")
        _delete(_base_url() + "/_apis/wit/workitems/" + str(probe_id) + "?destroy=true&api-version=7.0", pat)
        print("  Probe deleted."); return True
    if status == 400:
        print("  Write OK (400 = write allowed)"); return True
    print("  Unexpected " + str(status) + " — proceeding"); return True
 
 
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# State discovery (cached per work item type)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
_STATE_CACHE = {}
 
def discover_states(item_id, wi_type, pat):
    if wi_type in _STATE_CACHE:
        return _STATE_CACHE[wi_type]
    proj_enc = urllib.parse.quote(PROJECT, safe="")
    type_enc = urllib.parse.quote(wi_type, safe="")
    url = ("https://dev.azure.com/" + ORG + "/" + proj_enc
           + "/_apis/wit/workitemtypes/" + type_enc + "/states?api-version=7.0")
    status, data = _get(url, pat)
    states = [s["name"] for s in data.get("value", [])] if status == 200 else []
    if not states:
        states = ["New", "Active", "Resolved", "Closed"]
    print("    [Discovery] " + wi_type + " states: " + str(states))
    lower_map = {s.lower(): s for s in states}
    def pick(*kw):
        for k in kw:
            if k in lower_map: return lower_map[k]
        return states[0]
    result = {
        "New":      pick("new", "to do", "proposed"),
        "Active":   pick("active", "in progress", "doing", "committed"),
        "Resolved": pick("resolved", "done"),
        "Closed":   pick("closed", "done", "resolved", "complete"),
    }
    _STATE_CACHE[wi_type] = result
    return result
 
 
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 0: Project Summary (as Epic with full metadata)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
def create_project_summary(pat, dry_run=False, delay=0.2):
    """
    Creates an Epic work item containing all project metadata from projects.csv.
    This ensures project info (client, delivery type, dates, hours, etc.) is
    visible inside Azure DevOps.
    """
    print()
    print(SUBSEP)
    print("  PHASE 0: Project Summary Epic")
    print(SUBSEP)
 
    p = PROJECT_INFO
    title = "[Project] " + p["project_name"] + " — " + p["client_name"]
 
    desc = (
        "<h2>Project Summary</h2>"
        "<table border='1' cellpadding='6' cellspacing='0'>"
        "<tr><td><b>Project ID</b></td><td>" + p["project_id"] + "</td></tr>"
        "<tr><td><b>Project Name</b></td><td>" + p["project_name"] + "</td></tr>"
        "<tr><td><b>Client</b></td><td>" + p["client_name"] + "</td></tr>"
        "<tr><td><b>Delivery Type</b></td><td>" + p["delivery_type"] + "</td></tr>"
        "<tr><td><b>Project Manager</b></td><td>" + p["project_manager"] + "</td></tr>"
        "<tr><td><b>Start Date</b></td><td>" + p["start_date"] + "</td></tr>"
        "<tr><td><b>Target End Date</b></td><td>" + p["target_end_date"] + "</td></tr>"
        "<tr><td><b>Status</b></td><td>" + p["current_status"] + "</td></tr>"
        "<tr><td><b>Priority</b></td><td>" + p["priority"] + "</td></tr>"
        "<tr><td><b>Planned Total Hours</b></td><td>" + str(p["planned_total_hours"]) + "</td></tr>"
        "</table>"
    )
 
    area_path = PROJECT + "\\" + AREA_NAME
    tags = AREA_NAME + "; Project Summary; " + p["priority"]
 
    print("  " + title)
 
    if dry_run:
        print("    -> DRY RUN")
        return
 
    create_body = [
        {"op": "add", "path": "/fields/System.Title",       "value": title},
        {"op": "add", "path": "/fields/System.AreaPath",    "value": area_path},
        {"op": "add", "path": "/fields/System.Description", "value": desc},
        {"op": "add", "path": "/fields/System.Tags",        "value": tags},
        {"op": "add", "path": "/fields/System.AssignedTo",
         "value": "vasudev.makhija@maqsoftware.com"},
    ]
 
    # Add start/end dates if available
    if p.get("start_date"):
        create_body.append({
            "op": "add",
            "path": "/fields/Microsoft.VSTS.Scheduling.StartDate",
            "value": p["start_date"] + "T00:00:00Z",
        })
    if p.get("target_end_date"):
        create_body.append({
            "op": "add",
            "path": "/fields/Microsoft.VSTS.Scheduling.TargetDate",
            "value": p["target_end_date"] + "T00:00:00Z",
        })
 
    c_status, c_resp = _patch(_wi_create_url("Epic"), create_body, pat)
 
    if c_status in (200, 201):
        item_id = c_resp.get("id")
        print("    -> OK #" + str(item_id))
    else:
        err = str(c_resp.get("error", ""))[:80]
        print("    -> FAIL [" + str(c_status) + "] " + err)
 
    time.sleep(delay)
 
 
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 1: Area Path
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
def create_area_path(pat, dry_run=False):
    print()
    print(SUBSEP)
    print("  PHASE 1: Area Path — " + AREA_NAME)
    print(SUBSEP)
    if dry_run:
        print("  " + AREA_NAME + "  -> DRY RUN"); return True
    url  = _base_url() + "/_apis/wit/classificationnodes/areas?api-version=7.0"
    body = {"name": AREA_NAME}
    status, resp = _post(url, body, pat)
    if status in (200, 201):
        print("  " + AREA_NAME + "  -> OK"); return True
    elif status == 409:
        print("  " + AREA_NAME + "  -> EXISTS (ok)"); return True
    else:
        err = str(resp.get("error", ""))[:80]
        print("  " + AREA_NAME + "  -> FAIL [" + str(status) + "] " + err); return False
 
 
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 2: Iterations (Sprints)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
def create_iterations(pat, dry_run=False, delay=0.2):
    print()
    print(SUBSEP)
    print("  PHASE 2: Iterations (Sprints)")
    print(SUBSEP)
 
    # Step 1: Create parent iteration node for this project
    print("  Creating parent iteration: " + AREA_NAME)
    if not dry_run:
        url  = _base_url() + "/_apis/wit/classificationnodes/iterations?api-version=7.0"
        body = {"name": AREA_NAME}
        status, resp = _post(url, body, pat)
        tag = "OK" if status in (200, 201) else ("EXISTS" if status == 409 else "FAIL " + str(status))
        print("    -> " + tag)
        time.sleep(delay)
 
    # Step 2: Create each sprint under the parent
    created = 0
    for sid, info in SPRINTS.items():
        label = AREA_NAME + " / " + info["name"]
        if dry_run:
            print("  " + label + "  -> DRY RUN"); created += 1; continue
 
        parent_enc = urllib.parse.quote(AREA_NAME, safe="")
        url = (_base_url() + "/_apis/wit/classificationnodes/iterations/"
               + parent_enc + "?api-version=7.0")
        body = {"name": info["name"]}
        # Only add dates if they exist
        if info.get("start") and info.get("end"):
            body["attributes"] = {
                "startDate":  info["start"] + "T00:00:00Z",
                "finishDate": info["end"]   + "T00:00:00Z",
            }
        status, resp = _post(url, body, pat)
        tag = "OK" if status in (200, 201) else ("EXISTS" if status == 409 else "FAIL " + str(status))
        print("  " + label + "  -> " + tag)
        created += 1
        time.sleep(delay)
 
    print("  Iterations created: " + str(created))
 
    # Step 3: Subscribe iterations to the team board
    #   Without this, iterations exist in Project Settings but do NOT
    #   appear on the team's sprint boards / backlog.
    print()
    print("  Subscribing iterations to team sprint board...")
 
    if dry_run:
        for sid, info in SPRINTS.items():
            print("    " + info["name"] + "  -> DRY RUN (subscribe)")
        return
 
    # Detect team name (default is "<ProjectName> Team")
    team_name = PROJECT + " Team"
    team_enc  = urllib.parse.quote(team_name, safe="")
 
    for sid, info in SPRINTS.items():
        sprint_name = info["name"]
 
        # Get the iteration node ID (identifier GUID)
        path_enc = urllib.parse.quote(AREA_NAME + "/" + sprint_name, safe="")
        node_url = (_base_url()
                    + "/_apis/wit/classificationnodes/iterations/"
                    + path_enc + "?api-version=7.0")
        n_status, n_resp = _get(node_url, pat)
 
        if n_status != 200:
            print("    " + sprint_name + "  -> Could not find node (" + str(n_status) + ")")
            time.sleep(delay)
            continue
 
        node_id = n_resp.get("identifier", "")
        if not node_id:
            print("    " + sprint_name + "  -> No identifier found")
            time.sleep(delay)
            continue
 
        # POST to team iteration settings to subscribe
        team_url = ("https://dev.azure.com/" + ORG + "/" + PROJECT
                    + "/" + team_enc
                    + "/_apis/work/teamsettings/iterations?api-version=7.0")
        body = {"id": node_id}
        t_status, t_resp = _post(team_url, body, pat)
 
        if t_status in (200, 201):
            print("    " + sprint_name + "  -> Subscribed OK")
        elif t_status == 409 or (t_status == 400 and "already" in str(t_resp).lower()):
            print("    " + sprint_name + "  -> Already subscribed")
        else:
            err = str(t_resp.get("error", ""))[:80]
            print("    " + sprint_name + "  -> FAIL [" + str(t_status) + "] " + err)
 
        time.sleep(delay)
 
    print("  Team subscription done.")
 
 
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 3: Work Items
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
def _transition_to_state(item_id, wi_type, logical_state, pat):
    """Move a work item from New to the target state, using intermediate steps if needed."""
    if logical_state in ("New", "new", ""):
        return "New"
 
    state_map  = discover_states(item_id, wi_type, pat)
    real_state = state_map.get(logical_state, logical_state)
 
    update_body = [{"op": "add", "path": "/fields/System.State", "value": real_state}]
    u_status, _ = _patch(_wi_update_url(item_id), update_body, pat)
    if u_status in (200, 201):
        return real_state
 
    # Try intermediate transitions: New -> Active -> Resolved -> Closed
    if logical_state in ("Closed", "Resolved"):
        active_s = state_map.get("Active", "Active")
        _patch(_wi_update_url(item_id), [{"op": "add", "path": "/fields/System.State", "value": active_s}], pat)
        time.sleep(0.1)
        if logical_state == "Closed" and "Resolved" in state_map:
            _patch(_wi_update_url(item_id), [{"op": "add", "path": "/fields/System.State", "value": state_map["Resolved"]}], pat)
            time.sleep(0.1)
        u2_status, _ = _patch(_wi_update_url(item_id), update_body, pat)
        if u2_status in (200, 201):
            return real_state
 
    return "New (state update failed)"
 
 
def create_work_items(pat, dry_run=False, delay=0.2):
    print()
    print(SUBSEP)
    print("  PHASE 3: Work Items — " + str(len(WORK_ITEMS)) + " items")
    print(SUBSEP)
 
    total   = len(WORK_ITEMS)
    created = []
    failed  = []
 
    for idx, (sprint_id, wi_type, title, state, points, priority, assigned, blocked) in enumerate(WORK_ITEMS, 1):
        sprint_info    = SPRINTS.get(sprint_id, {})
        sprint_name    = sprint_info.get("name", sprint_id)
        area_path      = PROJECT + "\\" + AREA_NAME
        iteration_path = PROJECT + "\\" + AREA_NAME + "\\" + sprint_name
 
        icon = {"Issue": "I", "Task": "T"}.get(wi_type, "?")
        pct  = int((idx / total) * 100)
        line = ("  [" + icon + "] [" + str(idx).zfill(2) + "/" + str(total) + "]"
                + " (" + str(pct).rjust(3) + "%)"
                + " " + wi_type.ljust(12) + " " + state.ljust(10) + " " + title[:45])
 
        if dry_run:
            print(line + "  -> DRY RUN"); continue
 
        # Step 1: Create in New state
        create_body = [
            {"op": "add", "path": "/fields/System.Title",         "value": title},
            {"op": "add", "path": "/fields/System.AreaPath",      "value": area_path},
            {"op": "add", "path": "/fields/System.IterationPath", "value": iteration_path},
        ]
        if points is not None:
            create_body.append({
                "op": "add", "path": "/fields/Microsoft.VSTS.Scheduling.Effort",
                "value": float(points),
            })
        if priority:
            create_body.append({
                "op": "add", "path": "/fields/Microsoft.VSTS.Common.Priority",
                "value": int(priority),
            })
 
        tags_list = [AREA_NAME]
        if blocked:
            tags_list.append("Blocked")
        create_body.append({
            "op": "add", "path": "/fields/System.Tags", "value": "; ".join(tags_list),
        })
        create_body.append({
            "op": "add", "path": "/fields/System.AssignedTo", "value": "vasudev.makhija@maqsoftware.com",
        })
 
        c_status, c_resp = _patch(_wi_create_url(wi_type), create_body, pat)
 
        if c_status not in (200, 201):
            err = str(c_resp.get("error", ""))[:60]
            print(line + "  -> FAIL [" + str(c_status) + "] " + err)
            failed.append(title)
            if c_status in (401, 403):
                print("\n  Stopping — auth error."); break
            time.sleep(delay); continue
 
        item_id = c_resp.get("id")
 
        # Step 2: Transition state
        final_state = _transition_to_state(item_id, wi_type, state, pat)
        print(line + "  -> OK #" + str(item_id) + " [" + final_state + "]")
        created.append(item_id)
        time.sleep(delay)
 
    print("  Work Items — created: " + str(len(created)) + ", failed: " + str(len(failed)))
 
 
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 4: Milestones (as Epics)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
def create_milestones(pat, dry_run=False, delay=0.2):
    print()
    print(SUBSEP)
    print("  PHASE 4: Milestones — " + str(len(MILESTONES)) + " epics")
    print(SUBSEP)
 
    created = []
    for idx, (ms_name, due_date, status, delay_d, owner, notes) in enumerate(MILESTONES, 1):
        title     = "[Milestone] " + ms_name
        area_path = PROJECT + "\\" + AREA_NAME
        line      = "  [M] [" + str(idx) + "/" + str(len(MILESTONES)) + "] " + ms_name[:45]
 
        if dry_run:
            print(line + "  -> DRY RUN"); created.append(title); continue
 
        state_map = {"Completed": "Closed", "Delayed": "Active", "Watchlist": "Active", "On Track": "Active"}
        logical_state = state_map.get(status, "New")
 
        desc = ("<b>Milestone:</b> " + ms_name + "<br>"
                + "<b>Project:</b> " + AREA_NAME + " (" + PROJECT_ID + ")<br>"
                + "<b>Due Date:</b> " + due_date + "<br>"
                + "<b>Status:</b> " + status + "<br>"
                + "<b>Delay (days):</b> " + str(delay_d) + "<br>"
                + "<b>Owner:</b> " + owner + "<br>"
                + "<b>Notes:</b> " + notes)
 
        create_body = [
            {"op": "add", "path": "/fields/System.Title",       "value": title},
            {"op": "add", "path": "/fields/System.AreaPath",    "value": area_path},
            {"op": "add", "path": "/fields/System.Description", "value": desc},
            {"op": "add", "path": "/fields/System.Tags",
              "value": AREA_NAME + "; Milestone; " + status},
        ]
        if due_date:
            create_body.append({
                "op": "add", "path": "/fields/Microsoft.VSTS.Scheduling.TargetDate",
                "value": due_date + "T00:00:00Z",
            })
 
        create_body.append({
            "op": "add", "path": "/fields/System.AssignedTo", "value": "vasudev.makhija@maqsoftware.com",
        })
        c_status, c_resp = _patch(_wi_create_url("Epic"), create_body, pat)
        if c_status not in (200, 201):
            print(line + "  -> FAIL [" + str(c_status) + "]"); time.sleep(delay); continue
 
        item_id = c_resp.get("id")
        _transition_to_state(item_id, "Epic", logical_state, pat)
        print(line + "  -> OK #" + str(item_id))
        created.append(item_id)
        time.sleep(delay)
 
    print("  Milestones done: " + str(len(created)))
 
 
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 5: Risks (as Issues, fallback to Task)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
def create_risks(pat, dry_run=False, delay=0.2):
    print()
    print(SUBSEP)
    print("  PHASE 5: Risks — " + str(len(RISKS)) + " issues")
    print(SUBSEP)
 
    if not RISKS:
        print("  No risks for this project."); return
 
    created  = []
    wi_type  = "Issue"
 
    for idx, (risk_title, severity, r_status, mitigation, owner) in enumerate(RISKS, 1):
        title     = "[Risk] " + risk_title
        area_path = PROJECT + "\\" + AREA_NAME
        pri_map   = {"high": 1, "medium": 2, "low": 3}
        priority  = pri_map.get(severity.lower(), 4)
        line      = "  [R] [" + str(idx) + "/" + str(len(RISKS)) + "] " + risk_title[:45]
 
        if dry_run:
            print(line + "  -> DRY RUN"); created.append(title); continue
 
        desc = ("<b>Risk:</b> " + risk_title + "<br>"
                + "<b>Project:</b> " + AREA_NAME + " (" + PROJECT_ID + ")<br>"
                + "<b>Severity:</b> " + severity + "<br>"
                + "<b>Status:</b> " + r_status + "<br>"
                + "<b>Mitigation:</b> " + mitigation + "<br>"
                + "<b>Owner:</b> " + owner)
 
        create_body = [
            {"op": "add", "path": "/fields/System.Title",                   "value": title},
            {"op": "add", "path": "/fields/System.AreaPath",                "value": area_path},
            {"op": "add", "path": "/fields/System.Description",             "value": desc},
            {"op": "add", "path": "/fields/Microsoft.VSTS.Common.Priority", "value": priority},
            {"op": "add", "path": "/fields/System.Tags",
              "value": AREA_NAME + "; Risk; " + severity},
        ]
 
        create_body.append({
            "op": "add", "path": "/fields/System.AssignedTo", "value": "vasudev.makhija@maqsoftware.com",
        })
        c_status, c_resp = _patch(_wi_create_url(wi_type), create_body, pat)
 
        # Fallback to Task if Issue type unavailable
        if c_status not in (200, 201) and wi_type == "Issue":
            print("    (Issue type unavailable, falling back to Task)")
            wi_type = "Task"
            c_status, c_resp = _patch(_wi_create_url(wi_type), create_body, pat)
 
        if c_status not in (200, 201):
            print(line + "  -> FAIL [" + str(c_status) + "]"); time.sleep(delay); continue
 
        item_id = c_resp.get("id")
        print(line + "  -> OK #" + str(item_id))
        created.append(item_id)
        time.sleep(delay)
 
    print("  Risks done: " + str(len(created)))
 
 
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
def main():
    global ORG, PROJECT, PAT
 
    parser = argparse.ArgumentParser(description="Seed Azure DevOps — Gamma (P003)")
    parser.add_argument("--pat",      type=str,   default=None,  help="Azure DevOps PAT")
    parser.add_argument("--org",      type=str,   default=None,  help="Azure DevOps org")
    parser.add_argument("--project",  type=str,   default=None,  help="Azure DevOps project")
    parser.add_argument("--dry-run",  action="store_true",       help="Print plan only")
    parser.add_argument("--delay",    type=float, default=0.2,   help="Delay between calls (s)")
    parser.add_argument("--skip-areas",      action="store_true")
    parser.add_argument("--skip-iterations", action="store_true")
    parser.add_argument("--skip-work-items", action="store_true")
    parser.add_argument("--skip-milestones", action="store_true")
    parser.add_argument("--skip-risks",      action="store_true")
    args = parser.parse_args()
 
    if args.pat:     PAT = args.pat
    if args.org:     ORG = args.org
    if args.project: PROJECT = args.project
 
    print()
    print(SEP)
    print("  Azure DevOps Seeder — Gamma (P003)")
    print(SEP)
    print("  Org:       " + ORG)
    print("  Project:   " + PROJECT)
    print("  Area:      " + AREA_NAME)
    print("  Mode:      " + ("DRY RUN" if args.dry_run else "LIVE"))
    print("  Items:     " + str(len(WORK_ITEMS)) + " work items, "
          + str(len(MILESTONES)) + " milestones, " + str(len(RISKS)) + " risks")
    print(SEP)
    print()
 
    if not args.dry_run:
        print("Checking connection...")
        if not check_connection(PAT): sys.exit(1)
        print()
        if not check_write(PAT): sys.exit(1)
        print()
 
    # Phase 0: Project summary epic
    create_project_summary(PAT, args.dry_run, args.delay)
 
    if not args.skip_areas:      create_area_path(PAT, args.dry_run)
    if not args.skip_iterations: create_iterations(PAT, args.dry_run, args.delay)
    if not args.skip_work_items: create_work_items(PAT, args.dry_run, args.delay)
    if not args.skip_milestones: create_milestones(PAT, args.dry_run, args.delay)
    if not args.skip_risks:      create_risks(PAT, args.dry_run, args.delay)
 
    print()
    print(SEP)
    print("  DONE — Gamma (P003) seeding complete")
    print(SEP)
    print()
 
 
if __name__ == "__main__":
    main()