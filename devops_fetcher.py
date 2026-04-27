import requests
import base64
import chromadb
from datetime import datetime
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import os
from dotenv import load_dotenv

load_dotenv()
 
# Try to use sentence_transformers; fall back to sklearn if not available
print("Loading machine learning models (this may take a minute on the first run)...")
try:
    from sentence_transformers import SentenceTransformer
    embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    USE_SKLEARN = False
except Exception as e:
    print(f"Note: SentenceTransformer unavailable ({type(e).__name__}), using sklearn embeddings")
    from sklearn.feature_extraction.text import TfidfVectorizer
    embed_model = None
    USE_SKLEARN = True
 
DEVOPS_ORG = "Your Organization"  # Update with your Azure DevOps organization name

PAT_TOKEN = os.getenv("AZURE_DEVOPS_PAT")  # Update with your Azure DevOps PAT
PROJECTS   = ["Alpha", "Beta", "Gamma"]
 
# Create a requests session with retry logic
def create_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
 
def encode_documents(documents):
    """Encode documents using available embedding method"""
    if USE_SKLEARN:
        # Use TF-IDF for simple keyword-based embeddings
        vectorizer = TfidfVectorizer(max_features=300, stop_words='english')
        try:
            embeddings = vectorizer.fit_transform(documents).toarray().tolist()
        except:
            # Fallback: return random embeddings if vectorizer fails
            import numpy as np
            embeddings = np.random.rand(len(documents), 300).tolist()
        return embeddings
    else:
        # Use sentence_transformers
        return embed_model.encode(documents).tolist()
 
def get_headers():
    token = base64.b64encode(f":{PAT_TOKEN}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type":  "application/json"
    }
 
# ── Fetch work items ──────────────────────────────────────
def fetch_work_items(project_name: str, session=None) -> list:
    if session is None:
        session = create_session()
   
    print(f"  Fetching work items for {project_name}...")
    wiql_url = (
        f"https://dev.azure.com/{DEVOPS_ORG}/{project_name}"
        f"/_apis/wit/wiql?api-version=7.0"
    )
    wiql_query = {
        "query": f"""
            SELECT [System.Id]
            FROM WorkItems
            WHERE [System.TeamProject] = '{project_name}'
            ORDER BY [System.ChangedDate] DESC
        """
    }
   
    try:
        r = session.post(wiql_url, headers=get_headers(), json=wiql_query, timeout=30)
        if r.status_code != 200:
            print(f"  Error: {r.status_code} {r.text}")
            return []
 
        refs = r.json().get("workItems", [])
        if not refs:
            return []
 
        ids     = ",".join([str(i["id"]) for i in refs[:200]])
        det_url = (
            f"https://dev.azure.com/{DEVOPS_ORG}/{project_name}"
            f"/_apis/wit/workitems?ids={ids}"
            f"&fields=System.Id,System.Title,System.WorkItemType,"
            f"System.State,System.AssignedTo,Microsoft.VSTS.Common.Priority,"
            f"Microsoft.VSTS.Scheduling.StoryPoints,System.IterationPath,"
            f"System.Tags,Microsoft.VSTS.Common.Severity"
            f"&api-version=7.0"
        )
       
        # Add delay between requests to avoid rate limiting
        time.sleep(1)
       
        dr = session.get(det_url, headers=get_headers(), timeout=30)
        if dr.status_code != 200:
            print(f"  Error fetching work item details: {dr.status_code}")
            return []
 
        items = dr.json().get("value", [])
        print(f"  Found {len(items)} work items")
        return items
   
    except requests.exceptions.Timeout:
        print(f"  Timeout error: Request took too long for {project_name}")
        return []
    except requests.exceptions.ConnectionError as e:
        print(f"  Connection error for {project_name}: {str(e)}")
        return []
    except Exception as e:
        print(f"  Unexpected error fetching work items for {project_name}: {str(e)}")
        return []
 
# ── Fetch sprints with capacity data ─────────────────────
def fetch_sprints(project_name: str, session=None) -> list:
    if session is None:
        session = create_session()
   
    print(f"  Fetching sprints for {project_name}...")
    url = (
        f"https://dev.azure.com/{DEVOPS_ORG}/{project_name}"
        f"/_apis/work/teamsettings/iterations?api-version=7.0"
    )
   
    try:
        time.sleep(1)  # Delay to avoid rate limiting
        r = session.get(url, headers=get_headers(), timeout=30)
        if r.status_code != 200:
            print(f"  Error fetching sprints: {r.status_code}")
            return []
        sprints = r.json().get("value", [])
        print(f"  Found {len(sprints)} sprints")
        return sprints
   
    except requests.exceptions.Timeout:
        print(f"  Timeout error fetching sprints for {project_name}")
        return []
    except requests.exceptions.ConnectionError as e:
        print(f"  Connection error fetching sprints for {project_name}: {str(e)}")
        return []
    except Exception as e:
        print(f"  Unexpected error fetching sprints for {project_name}: {str(e)}")
        return []
 
# ── Fetch sprint work items (for per-sprint completion) ───
def fetch_sprint_items(project_name: str, sprint_id: str, session=None) -> dict:
    """
    Gets work items in a specific sprint and calculates
    completion stats for that sprint only.
    """
    if session is None:
        session = create_session()
   
    url = (
        f"https://dev.azure.com/{DEVOPS_ORG}/{project_name}"
        f"/_apis/work/teamsettings/iterations/{sprint_id}/workitems"
        f"?api-version=7.0"
    )
   
    try:
        time.sleep(1)  # Delay to avoid rate limiting
        r = session.get(url, headers=get_headers(), timeout=30)
        if r.status_code != 200:
            return {"planned": 0, "completed": 0, "blocked": 0}
 
        relations = r.json().get("workItemRelations", [])
        if not relations:
            return {"planned": 0, "completed": 0, "blocked": 0}
 
        # Get IDs
        ids = [str(rel["target"]["id"]) for rel in relations if rel.get("target")]
        if not ids:
            return {"planned": 0, "completed": 0, "blocked": 0}
 
        ids_str = ",".join(ids[:100])
        det_url = (
            f"https://dev.azure.com/{DEVOPS_ORG}/{project_name}"
            f"/_apis/wit/workitems?ids={ids_str}"
            f"&fields=System.State,Microsoft.VSTS.Scheduling.StoryPoints,"
            f"System.Tags,System.WorkItemType"
            f"&api-version=7.0"
        )
       
        time.sleep(1)  # Delay to avoid rate limiting
        dr = session.get(det_url, headers=get_headers(), timeout=30)
        if dr.status_code != 200:
            return {"planned": 0, "completed": 0, "blocked": 0}
 
        items   = dr.json().get("value", [])
        planned = 0
        completed = 0
        blocked = 0
 
        for item in items:
            f      = item.get("fields", {})
            state  = f.get("System.State", "")
            points = float(f.get("Microsoft.VSTS.Scheduling.StoryPoints") or 1)
            tags   = (f.get("System.Tags") or "").lower()
            wtype  = f.get("System.WorkItemType", "")
 
            # Skip epics and features — count only tasks/stories/bugs
            if wtype in ["Epic", "Feature"]:
                continue
 
            planned += points
 
            if state in ["Done", "Closed", "Resolved", "Completed"]:
                completed += points
 
            if "blocked" in tags or state == "Blocked":
                blocked += 1
 
        return {
            "planned":   planned,
            "completed": completed,
            "blocked":   blocked,
            "items":     len(items)
        }
   
    except requests.exceptions.Timeout:
        print(f"  Timeout error fetching sprint items for {project_name}")
        return {"planned": 0, "completed": 0, "blocked": 0}
    except requests.exceptions.ConnectionError as e:
        print(f"  Connection error fetching sprint items for {project_name}: {str(e)}")
        return {"planned": 0, "completed": 0, "blocked": 0}
    except Exception as e:
        print(f"  Unexpected error fetching sprint items for {project_name}: {str(e)}")
        return {"planned": 0, "completed": 0, "blocked": 0}
 
# ── Build passages per project ────────────────────────────
def build_passages(project_name: str, work_items: list, sprints: list) -> tuple:
    documents = []
    metadatas = []
    ids       = []
 
    # ── Per-item passages ──
    total_planned   = 0.0
    total_completed = 0.0
    total_blocked   = 0
    bug_count       = 0
 
    for item in work_items:
        f        = item.get("fields", {})
        item_id  = str(item.get("id", ""))
        title    = f.get("System.Title", "Unknown")
        wtype    = f.get("System.WorkItemType", "Unknown")
        state    = f.get("System.State", "Unknown")
        assigned = f.get("System.AssignedTo", {})
        if isinstance(assigned, dict):
            assigned = assigned.get("displayName", "Unassigned")
        priority  = f.get("Microsoft.VSTS.Common.Priority", "")
        points    = float(f.get("Microsoft.VSTS.Scheduling.StoryPoints") or 1)
        iteration = f.get("System.IterationPath", "")
        tags      = (f.get("System.Tags") or "").lower()
 
        if wtype in ["Epic", "Feature"]:
            continue
 
        is_blocked = "blocked" in tags or state == "Blocked"
        if is_blocked:
            total_blocked += 1
 
        if wtype == "Bug" and state not in ["Done", "Closed", "Resolved"]:
            bug_count += 1
 
        total_planned += points
        if state in ["Done", "Closed", "Resolved", "Completed"]:
            total_completed += points
 
        text = (
            f"Work item '{title}' (type: {wtype}) "
            f"in project {project_name}, sprint {iteration}. "
            f"State: {state}. Priority: {priority}. "
            f"Story points: {points}. Assigned to: {assigned}. "
            f"Blocked: {is_blocked}. "
            f"Live data from Azure DevOps."
        )
        documents.append(text)
        metadatas.append({
            "source":     "work_item",
            "project_id": project_name,
            "item_id":    item_id
        })
        ids.append(f"devops_wi_{project_name}_{item_id}")
 
    # ── Project summary passage with real calculated metrics ──
    completion_pct = round(
        (total_completed / total_planned * 100), 1
    ) if total_planned > 0 else 0.0
 
    carryover_pct = round(
        ((total_planned - total_completed) / total_planned * 100), 1
    ) if total_planned > 0 else 0.0
 
    summary = (
        f"Project {project_name} live summary from Azure DevOps. "
        f"Total active work items: {len(work_items)}. "
        f"Planned story points: {total_planned}. "
        f"Completed story points: {total_completed}. "
        f"Completion percentage: {completion_pct}%. "
        f"Velocity: {completion_pct}%. "
        f"Carryover percentage: {carryover_pct}%. "
        f"Blocked items: {total_blocked}. "
        f"Open bugs: {bug_count}. "
        f"Fetched at: {datetime.now().strftime('%Y-%m-%d %H:%M')}."
    )
    documents.append(summary)
    metadatas.append({
        "source":     "project_summary",
        "project_id": project_name
    })
    ids.append(f"devops_summary_{project_name}")
 
    # ── Sprint passages ──
    for i, sprint in enumerate(sprints):
        name       = sprint.get("name", "Unknown")
        attributes = sprint.get("attributes", {})
        start      = attributes.get("startDate", "")[:10] if attributes.get("startDate") else "TBD"
        end        = attributes.get("finishDate", "")[:10] if attributes.get("finishDate") else "TBD"
        timeframe  = attributes.get("timeFrame", "unknown")
 
        text = (
            f"Sprint '{name}' for project {project_name}. "
            f"Start: {start}. End: {end}. "
            f"Timeframe: {timeframe}. "
            f"Live data from Azure DevOps."
        )
        documents.append(text)
        metadatas.append({
            "source":     "sprint",
            "project_id": project_name
        })
        ids.append(f"devops_sprint_{project_name}_{i}")
 
    print(
        f"  Summary: {len(work_items)} items, "
        f"{completion_pct}% complete, "
        f"{total_blocked} blocked, "
        f"{bug_count} bugs"
    )
    return documents, metadatas, ids
 
# ── Main refresh function ─────────────────────────────────
def refresh_devops_data(collection) -> int:
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Refreshing from Azure DevOps...")
 
    session = create_session()  # Create session once for reuse
    all_documents = []
    all_metadatas = []
    all_ids       = []
 
    for project_name in PROJECTS:
        print(f"\nProject: {project_name}")
 
        # Clear old entries
        try:
            existing = collection.get(where={"project_id": project_name})
            if existing["ids"]:
                collection.delete(ids=existing["ids"])
                print(f"  Cleared {len(existing['ids'])} old entries")
        except Exception as e:
            print(f"  Note: {e}")
 
        # Fetch fresh data with session
        work_items = fetch_work_items(project_name, session)
        sprints    = fetch_sprints(project_name, session)
 
        # Build passages with real metrics
        docs, metas, doc_ids = build_passages(project_name, work_items, sprints)
        all_documents.extend(docs)
        all_metadatas.extend(metas)
        all_ids.extend(doc_ids)
 
    # Embed and store
    if all_documents:
        print(f"\nEmbedding {len(all_documents)} passages...")
        embeddings = encode_documents(all_documents)
        collection.add(
            documents=all_documents,
            embeddings=embeddings,
            metadatas=all_metadatas,
            ids=all_ids
        )
        print(f"ChromaDB updated — {len(all_documents)} passages added")
 
    session.close()  # Close session when done
    return len(all_documents)
 
 
if __name__ == "__main__":
    client     = chromadb.PersistentClient(path="./chroma_db")
    collection = client.get_or_create_collection("maq_projects")
    count      = refresh_devops_data(collection)
    print(f"\nTotal passages in ChromaDB: {collection.count()}")