import chromadb
import json
from sentence_transformers import SentenceTransformer
from llama_index.core import Document
from llama_index.retrievers.bm25 import BM25Retriever
from devops_fetcher import refresh_devops_data

# ── Setup ──────────────────────────────────────────────────
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection     = chroma_client.get_collection("maq_projects")
embed_model    = SentenceTransformer("all-MiniLM-L6-v2")

# Refresh live data from Azure DevOps before every run
try:
    refresh_devops_data(collection)
except Exception as e:
    print(f"Warning: Error refreshing DevOps data: {e}")
    print("Continuing with cached data...")

# Load all documents for BM25 (keyword search)
all_data  = collection.get(include=["documents", "metadatas"])
documents = all_data["documents"]
metadatas = all_data["metadatas"]

# Build BM25 index over same corpus
llama_docs     = [Document(text=d) for d in documents]
bm25_retriever = BM25Retriever.from_defaults(
    nodes=llama_docs, similarity_top_k=5
)

# ── Hybrid RAG function ────────────────────────────────────
def hybrid_retrieve(query: str, top_k: int = 5) -> list[dict]:
    # 1. Semantic search via ChromaDB
    query_embedding  = embed_model.encode([query]).tolist()
    semantic_results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )
    semantic_passages = list(zip(
        semantic_results["documents"][0],
        semantic_results["metadatas"][0]
    ))

    # 2. Keyword search via BM25
    bm25_results  = bm25_retriever.retrieve(query)
    bm25_passages = []
    for r in bm25_results:
        text = r.node.text
        if text in documents:
            idx  = documents.index(text)
            meta = metadatas[idx]
        else:
            meta = {"source": "unknown", "project_id": "unknown"}
        bm25_passages.append((text, meta))

    # 3. Merge and deduplicate
    seen   = set()
    merged = []
    for text, meta in semantic_passages + bm25_passages:
        if text not in seen:
            seen.add(text)
            merged.append({"text": text, "meta": meta})

    return merged[:top_k]

# ── Risk detection function ────────────────────────────────
def detect_risks(project_id: str) -> dict:
    all_passages = collection.get(
        where={"project_id": project_id},
        include=["documents", "metadatas"]
    )

    signals = {
        "project_id": project_id,
        "high_risks": [],
        "blocked_items": [],
        "delayed_milestones": [],
        "overloaded_weeks": [],
        "low_velocity_sprints": [],
        "metrics": {
            "completion_pct": 0.0,
            "carryover_pct": 0.0,
            "blocked_count": 0,
            "open_bugs": 0,
            "past_sprints": 0,
        }
    }

    for doc, meta in zip(all_passages["documents"], all_passages["metadatas"]):
        source = meta.get("source", "")

        if source == "project_summary":
            try:
                if "Completion percentage:" in doc:
                    signals["metrics"]["completion_pct"] = float(
                        doc.split("Completion percentage:")[1].split("%")[0].strip()
                    )
                if "Carryover percentage:" in doc:
                    signals["metrics"]["carryover_pct"] = float(
                        doc.split("Carryover percentage:")[1].split("%")[0].strip()
                    )
                if "Blocked items:" in doc:
                    signals["metrics"]["blocked_count"] = int(
                        doc.split("Blocked items:")[1].split(".")[0].strip()
                    )
                if "Open bugs:" in doc:
                    signals["metrics"]["open_bugs"] = int(
                        doc.split("Open bugs:")[1].split(".")[0].strip()
                    )
            except Exception:
                pass

        # DevOps work items — blocked detection
        if source == "work_item" and "Blocked: True" in doc:
            signals["blocked_items"].append(doc)

        # Past sprints are normal; track count and combine with low completion later.
        if source == "sprint" and "Timeframe: past" in doc:
            signals["metrics"]["past_sprints"] += 1

        # Keep old static checks in case static data still exists
        if source == "risk" and "High" in doc and "Open" in doc:
            signals["high_risks"].append(doc)

        if source == "milestone" and "Delayed" in doc:
            signals["delayed_milestones"].append(doc)

        if source == "timesheet" and "Utilization:" in doc:
            try:
                util = float(
                    doc.split("Utilization:")[1].split("%")[0].strip()
                )
                if util > 110:
                    signals["overloaded_weeks"].append(doc)
            except Exception:
                pass

    completion = signals["metrics"]["completion_pct"]
    carryover = signals["metrics"]["carryover_pct"]
    blocked = signals["metrics"]["blocked_count"]
    bugs = signals["metrics"]["open_bugs"]
    past_sprints = signals["metrics"]["past_sprints"]

    # High-risk signals
    if completion < 50:
        signals["high_risks"].append(
            f"{project_id} completion is {completion}% (below 50%)."
        )
    if blocked >= 3:
        signals["high_risks"].append(
            f"{project_id} has {blocked} blocked items (>=3)."
        )
    if carryover >= 50:
        signals["high_risks"].append(
            f"{project_id} carryover is {carryover}% (>=50%)."
        )
    if bugs >= 4:
        signals["high_risks"].append(
            f"{project_id} has {bugs} open bugs (>=4)."
        )

    # Medium-risk signals
    if 50 <= completion < 70:
        signals["low_velocity_sprints"].append(
            f"{project_id} completion is moderate at {completion}%."
        )
    if 1 <= blocked < 3:
        signals["blocked_items"].append(
            f"{project_id} has {blocked} blocked item(s)."
        )
    if 30 <= carryover < 50:
        signals["low_velocity_sprints"].append(
            f"{project_id} carryover is elevated at {carryover}%."
        )

    if past_sprints >= 2 and completion < 60:
        signals["delayed_milestones"].append(
            f"{project_id} has {past_sprints} past sprints with low completion ({completion}%)."
        )

    # Overall risk level
    if signals["high_risks"] or signals["delayed_milestones"]:
        signals["overall_risk"] = "HIGH"
    elif (
        signals["blocked_items"]
        or signals["low_velocity_sprints"]
        or signals["overloaded_weeks"]
    ):
        signals["overall_risk"] = "MEDIUM"
    else:
        signals["overall_risk"] = "LOW"

    return signals

# ── AutoGen Agent setup ────────────────────────────────────
import autogen

config_list = [
    {
        "model":    "llama3.2:latest",
        "base_url": "http://localhost:11434/v1",
        "api_key":  "ollama",
    }
]

llm_config = {"config_list": config_list, "temperature": 0}

retrieval_agent = autogen.AssistantAgent(
    name="DataRetrievalAgent",
    llm_config=llm_config,
    system_message="""You are a project health analyst for MAQ Software.
You answer questions about Power BI delivery projects using retrieved context.
Always base your answers only on the provided context.
When asked about project health, mention: status, risks, blocked items,
sprint velocity, and recommended actions.
Be concise and factual. Format your response clearly."""
)

user_proxy = autogen.UserProxyAgent(
    name="Manager",
    human_input_mode="NEVER",
    max_consecutive_auto_reply=1,
    code_execution_config=False
)

# ── Main query function ────────────────────────────────────
def answer_query(query: str):
    print(f"\nQuery: {query}")
    print("="*55)

    # Step 1: Refresh DevOps data before every query
    try:
        refresh_devops_data(collection)
    except Exception as e:
        print(f"Warning: Error refreshing DevOps data: {e}")
        print("Continuing with cached data...")

    # Step 2: Hybrid retrieve relevant passages
    passages = hybrid_retrieve(query, top_k=6)
    context  = "\n\n".join([p["text"] for p in passages])

    # Step 3: Run risk detection — use DevOps project names directly
    active_ids = ["Alpha", "Beta", "Gamma"]

    risk_summaries = []
    for pid in active_ids:
        risk = detect_risks(pid)
        risk_summaries.append(risk)
        print(
            f"{pid}: risk={risk['overall_risk']} | "
            f"completion={risk['metrics']['completion_pct']}% | "
            f"carryover={risk['metrics']['carryover_pct']}% | "
            f"blocked={risk['metrics']['blocked_count']} | "
            f"bugs={risk['metrics']['open_bugs']}"
        )

    risk_context = json.dumps(risk_summaries, indent=2)

    # Step 4: Build the full prompt
    full_prompt = f"""
Using the following retrieved project data, answer this question:
"{query}"

RETRIEVED CONTEXT:
{context}

RISK ANALYSIS:
{risk_context}

Provide a clear, structured answer covering:
1. Overall portfolio health
2. At-risk projects and why
3. Key metrics (completion, carryover, blocked items, open bugs, sprint status)
4. Recommended actions
"""

    # Step 5: Trigger the agent
    user_proxy.initiate_chat(
        retrieval_agent,
        message=full_prompt,
        max_turns=2
    )

# ── Run a test query ───────────────────────────────────────
if __name__ == "__main__":
    answer_query("What is the health of our active Power BI delivery projects?")