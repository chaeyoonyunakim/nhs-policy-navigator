"""
Generate demo narration MP3 via the /api/narrate endpoint.
Run with: python narrate.py
Requires the app to be running: python -m uvicorn app:app --reload
"""
import httpx

script = (
    "NHS Policy Navigator. An adaptive retrieval agent built for the MongoDB Agentic Evolution Hackathon. "
    "Here is what we built, and why it matters. "

    "The NHS 10 Year Health Plan sets out a bold vision for the future of healthcare in England. "
    "But a document this large, over 100 pages, is difficult to navigate. "
    "Policy questions often need an answer in seconds, not hours. "
    "That is the problem this agent solves. "

    "At its core, the system uses MongoDB Atlas as the retrieval backbone. "
    "586 chunks of the NHS plan are embedded using OpenAI and stored with both vector and full-text indexes. "
    "This gives us the flexibility to choose the right search strategy for each question. "

    "The first thing the agent does with every query is classify it. "
    "Is this a factual question, a conceptual one, a comparative question, or a gap analysis? "
    "That classification drives everything downstream. "

    "Factual questions go straight to text search against the plan. "
    "Conceptual and comparative questions trigger hybrid retrieval, combining semantic vector search with keyword matching, "
    "and pull in live context from the NHS England news feed. "
    "Gap analysis queries go furthest, pulling from the plan, live news, and NHS publications released after the plan itself was published in July 2025. "

    "This is the source routing layer. The agent decides where to look before it looks. "

    "Retrieved plan chunks are then re-ranked by an LLM. "
    "GPT-4o-mini scores each chunk against the original query from zero to ten, "
    "and only the most relevant chunks make it into the final answer. "
    "This cuts noise and keeps responses grounded. "

    "The agent also learns over time. "
    "Every query result is logged to MongoDB with a self-evaluation score. "
    "Once a query type has been seen five or more times, "
    "the agent automatically switches to whichever retrieval strategy has performed best historically. "
    "No manual tuning. It adapts. "

    "All of this is observable. "
    "Every step, classification, source routing, strategy selection, retrieval, reranking, evaluation, and generation, "
    "is traced via LangSmith. "
    "You can watch the agent reason in real time. "

    "The frontend surfaces everything the agent did: which sources were queried, "
    "what live news articles were found, which publications were referenced, "
    "and the relevance score of every plan chunk. "
    "Transparency is built in, not bolted on. "

    "This was built in one hackathon day. "
    "MongoDB Atlas made adaptive multi-source retrieval possible without managing separate infrastructure for search, storage, and logging. "
    "Everything lives in one place, and the agent gets smarter with every query. "

    "NHS Policy Navigator. Built on MongoDB. Designed for the people who make NHS policy decisions."
)

print("Sending narration request...")
print(f"Script length: {len(script)} characters")

try:
    r = httpx.post(
        "http://localhost:8000/api/narrate",
        json={"query": script},
        timeout=60.0
    )
    print(f"Status: {r.status_code}")
    print(f"Content-Type: {r.headers.get('content-type', 'unknown')}")

    if r.status_code == 200 and "audio" in r.headers.get("content-type", ""):
        with open("demo-narration.mp3", "wb") as f:
            f.write(r.content)
        print(f"Saved demo-narration.mp3 ({len(r.content):,} bytes)")
    else:
        print("Error response:")
        print(r.text[:500])
except httpx.ConnectError:
    print("Could not connect to localhost:8000 -- make sure the app is running:")
    print("  python -m uvicorn app:app --reload")
except Exception as e:
    print(f"Unexpected error: {e}")
