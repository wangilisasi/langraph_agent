# Adding a RAG Pipeline

Integrating Retrieval-Augmented Generation (RAG) into a LangGraph agent allows it to answer questions based on your private documents (PDFs, text files, code, etc.) rather than just the public web.

## Architecture Options

### Option 1: The "Retriever Tool" (Tool-based RAG)
This is the simplest to add to our current setup. We load a folder of documents, embed them into a local vector store (like FAISS or Chroma), and create a new `@tool` called `search_local_documents(query)`.
- **Pros:** Minimal changes to the graph (`agent.py`). The LLM decides when to search your documents in the same way it decides when to search the web.
- **Cons:** Relies on the LLM to choose the tool; doesn't automatically inject context for every single query.

### Option 2: The "RAG Router Node" (Classic RAG)
We modify `agent.py` so that before the `chatbot` node runs, a `retriever` node fetches relevant documents based on the user's query and injects them directly into the system prompt or messages.
- **Pros:** Guarantees that the LLM always has the local context available for every single question before it answers. 
- **Cons:** Slightly more complex graph routing. We'd have to handle when specifically to trigger this node versus bypassing it.

### Option 3: External Knowledge Base API (e.g., Pinecone/Weaviate)
We set up a persistent, cloud-hosted vector database. 
- **Pros:** Scalable to millions of documents.
- **Cons:** Overkill for a learning project. Requires API keys, cloud signups, and more bloated code.

## Chosen Implementation (Option 1)

**Dependencies Added:**
- `langchain-community`, `faiss-cpu`, `pypdf`, `langchain-huggingface`

**Implementation Details:**
- A `docs/` folder was created for storing local `.txt` and `.pdf` files.
- `tools.py` initializes a local **FAISS** index using lightweight, free **HuggingFaceEmbeddings** (`all-MiniLM-L6-v2`) that run entirely on the CPU.
- When the `search_local_documents` tool is called, it loads the documents, runs semantic search, and returns the top 3 most relevant passages.
- `agent.py` explicitly allows the LLM to determine when a query pertains to personal files and use the tool automatically.
