# CV Ingestion Agent (LangGraph → Neo4j)

A LangGraph agent that ingests a folder of CVs, extracts a structured talent
graph from each one with Claude, deduplicates entities across the whole batch,
embeds the key text fields, and writes everything into a Neo4j graph database.

```
 discover ─▶ parse ─▶ extract ─▶ deduplicate ─▶ embed ─▶ write_neo4j
```

| Node          | Responsibility                                                          |
| ------------- | ----------------------------------------------------------------------- |
| `discover`    | Scan `CV_FOLDER` for supported files (`.pdf`, `.docx`, `.txt`, `.md`).  |
| `parse`       | Extract raw text from each document.                                    |
| `extract`     | Claude (`claude-opus-4-8`) → structured CV via **structured outputs**.   |
| `deduplicate` | Merge Skills/Courses/Projects/Accomplishments within and across CVs.    |
| `embed`       | Voyage AI embeddings for Skill, Course, Project, Accomplishment text.   |
| `write_neo4j` | `MERGE` nodes + relationships, set embeddings, build vector indexes.    |

## Graph schema

Nodes and properties (from the supplied schema diagram):

- **Skill** `{uid, name, type: Mgmt|Tech, expertise_level: Basic|Intermediate|Expert, tags, is_missing: Yes|No}`
- **Course** `{name, is_certification: Yes|No, provider, validity}`
- **Project** `{name, company, start_date, end_date}`
- **Accomplishment** `{text, tags, quantitative_achievement}`

Relationships:

- `(Skill)-[:LEARNED_IN]->(Course)`
- `(Accomplishment)-[:USING]->(Skill)`
- `(Accomplishment)-[:GAINED_IN]->(Project)`

A `Candidate` anchor node is added on top of the diagram so each CV's data stays
attributable (see [ASSUMPTIONS.md](ASSUMPTIONS.md)).

## Quick start

```bash
# 1. Python 3.10+
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt

# 2. Configure
cp .env.example .env        # then fill in keys + Neo4j connection

# 3. Drop CVs into the folder pointed at by CV_FOLDER (default: ./data/cvs)

# 4. Run
python -m ingestion_agent.main            # uses CV_FOLDER from .env
python -m ingestion_agent.main --folder /path/to/cvs --dry-run
```

`--dry-run` runs the full pipeline (discover → embed) but skips the Neo4j write,
which is handy for verifying extraction without a database.

## Project layout

```
src/ingestion_agent/
  config.py          # .env-backed settings
  models.py          # Pydantic extraction schema (Claude structured output)
  state.py           # LangGraph state
  llm.py             # Claude extraction client
  embeddings.py      # Voyage AI embedding client
  neo4j_client.py    # Neo4j writer + schema/index setup
  graph.py           # LangGraph assembly
  main.py            # CLI entrypoint
  nodes/             # one module per graph node
```
