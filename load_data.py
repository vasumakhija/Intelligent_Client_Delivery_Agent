import pandas as pd
import chromadb
from sentence_transformers import SentenceTransformer
import json
from pathlib import Path


def ensure_unique_ids(raw_ids):
    """Append a suffix for repeated IDs so Chroma always gets unique keys."""
    seen = {}
    unique = []
    for value in raw_ids:
        key = str(value)
        count = seen.get(key, 0)
        if count == 0:
            unique.append(key)
        else:
            unique.append(f"{key}_{count}")
        seen[key] = count + 1
    return unique

# Load your CSV files
projects   = pd.read_csv("data/projects.csv")
sprints    = pd.read_csv("data/sprints.csv")
timesheets = pd.read_csv("data/timesheets.csv")

# Set up ChromaDB (saves locally in a folder called chroma_db)
client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_or_create_collection("maq_projects")

# Load embedding model (downloads once, runs locally forever)
model = SentenceTransformer("all-MiniLM-L6-v2")

documents = []
metadatas = []
ids = []

# Convert each project row into a text passage
for _, row in projects.iterrows():
    text = (
        f"Project {row['project_name']} for client {row['client_name']}. "
        f"Managed by {row['project_manager']}. "
        f"Status: {row['current_status']}. Priority: {row['priority']}. "
        f"Start: {row['start_date']}, Target end: {row['target_end_date']}. "
        f"Planned hours: {row['planned_total_hours']}. Active: {row['active_flag']}."
    )
    documents.append(text)
    metadatas.append({"source": "project", "project_id": str(row['project_id'])})
    ids.append(f"project_{row['project_id']}")

# Convert each sprint row into a text passage
for _, row in sprints.iterrows():
    text = (
        f"Sprint {row['sprint_name']} for project {row['project_id']}. "
        f"Planned points: {row['planned_story_points']}, "
        f"Completed: {row['completed_story_points']}, "
        f"Carryover: {row['carryover_story_points']}. "
        f"Blocked items: {row['blocked_items_count']}. "
        f"Open bugs: {row['open_bugs_count']}. "
        f"Sprint status: {row['sprint_status']}."
    )
    documents.append(text)
    metadatas.append({"source": "sprint", "project_id": str(row['project_id'])})
    ids.append(f"sprint_{row['sprint_id']}")

# Convert each timesheet row into a text passage
for _, row in timesheets.iterrows():
    text = (
        f"Timesheet for project {row['project_id']} week {row['week_start']}. "
        f"Planned hours: {row['planned_hours']}, Actual: {row['actual_hours']}. "
        f"Billable hours: {row['billable_hours']}. "
        f"Utilization: {row['utilization_percent']}%. "
        f"Approved: {row['approved_flag']}."
    )
    documents.append(text)
    metadatas.append({"source": "timesheet", "project_id": str(row['project_id'])})
    ids.append(f"timesheet_{row['project_id']}_{row['week_start']}")

# work_items.csv
work_items = pd.read_csv("data/work_items.csv")

for _, row in work_items.iterrows():
    text = (
        f"Work item '{row['title']}' (type: {row['work_item_type']}) "
        f"in project {row['project_id']}, sprint {row['sprint_id']}. "
        f"State: {row['state']}. Priority: {row['priority']}. "
        f"Story points: {row['story_points']}. Assigned to: {row['assigned_to']}. "
        f"Blocked: {row['blocked_flag']}. Due: {row['due_date']}."
    )
    documents.append(text)
    metadatas.append({"source": "work_item", "project_id": str(row['project_id'])})
    ids.append(f"workitem_{row['work_item_id']}")

# milestones.csv
milestones = pd.read_csv("data/milestones.csv")

for _, row in milestones.iterrows():
    text = (
        f"Milestone '{row['milestone_name']}' for project {row['project_id']}. "
        f"Due: {row['due_date']}. Status: {row['status']}. "
        f"Delay: {row['delay_days']} days. Owner: {row['owner']}. "
        f"Notes: {row['notes']}."
    )
    documents.append(text)
    metadatas.append({"source": "milestone", "project_id": str(row['project_id'])})
    ids.append(f"milestone_{row['project_id']}_{row['milestone_name'].replace(' ','_')}")

# risk.json
risk_file = Path("data/risks.json")
if not risk_file.exists():
    risk_file = Path("data/risk.json")

with risk_file.open("r", encoding="utf-8") as f:
    risks = json.load(f)

for i, row in enumerate(risks):
    text = (
        f"Risk identified for project {row['project_id']}: "
        f"'{row['risk_title']}'. "
        f"Severity: {row['severity']}. "
        f"Status: {row['status']}. "
        f"Mitigation plan: {row['mitigation']}. "
        f"Owner: {row['owner']}."
    )
    documents.append(text)
    metadatas.append({
        "source": "risk",
        "project_id": str(row['project_id']),
        "severity": row['severity'],
        "status": row['status']
    })
    ids.append(f"risk_{row['project_id']}_{i}")

# Embed everything and store in ChromaDB
print(f"Embedding {len(documents)} passages...")
ids = ensure_unique_ids(ids)
embeddings = model.encode(documents).tolist()
collection.upsert(documents=documents, embeddings=embeddings, metadatas=metadatas, ids=ids)
print("Done! ChromaDB loaded successfully.")
print(f"Total passages stored: {collection.count()}")