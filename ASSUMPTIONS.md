# Assumptions

The task left several things open ("assume things on your own"). These are the
decisions made, and why.

## Models & providers

1. **LLM = Claude `claude-opus-4-8` via the official `anthropic` SDK.** The task
   is an LLM extraction problem with no provider stated, so it defaults to the
   latest Claude model. Extraction uses **structured outputs**
   (`client.messages.parse`) so Claude returns a schema-validated object rather
   than free text we have to parse.
2. **Embeddings = Voyage AI (`voyage-3.5`, 1024-dim).** Anthropic does not offer
   an embeddings endpoint and recommends Voyage AI. The provider, model, and
   dimension are all configurable in `.env`, so swapping to another embedder is
   a config change, not a code change.

## Graph schema interpretation

3. **A `Candidate` node was added** on top of the four nodes in the diagram. The
   diagram shows Skill/Course/Project/Accomplishment but nothing tying a CV's
   data to the person it came from; without an anchor, two CVs would dissolve
   into one undifferentiated graph. `Candidate` connects via `HAS_SKILL`,
   `COMPLETED` (course), `WORKED_ON` (project), and `ACHIEVED` (accomplishment).
   The three relationships from the diagram are kept exactly as drawn.
4. **`Skill.UID`** is treated as the dedup key. The diagram explicitly labels it
   "Unique ID", which signals skills are meant to be shared, deduplicated
   entities. UID is a deterministic slug of the normalized skill name
   (`skill::aws`), so the same skill from different CVs becomes one node.
5. **`Skill.IsMissing`** defaults to `"No"` on ingestion. A skill found in a CV
   is, by definition, present. `IsMissing = "Yes"` is reserved for downstream
   gap-analysis (a required skill a candidate lacks) and is not produced here.
6. **`Course.Validity`** is captured as free text (e.g. "3 years", "" if not
   stated) rather than a parsed duration, because CVs phrase it inconsistently.
7. **Dates** (`Project.StartDate` / `EndDate`) are stored as the raw strings from
   the CV (e.g. "Aug 2022", "Present"). No date normalization is attempted, to
   avoid guessing at ambiguous formats.

## Deduplication strategy

8. **Skills and Courses are deduplicated globally** (shared across all
   candidates) — "AWS" is one node many candidates point to.
   - Skill key: normalized name → `skill::<slug>`.
   - Course key: normalized `(name, provider)`.
   - On conflict, the highest expertise level seen wins; tags are unioned.
9. **Projects and Accomplishments are deduplicated per candidate**, since they
   are personal history.
   - Project key: `(candidate, normalized name)`.
   - Accomplishment key: `(candidate, sha1(text))`.
10. **Relationships are inferred by name-matching** during extraction: Claude
    links each accomplishment to the skills it used and the project it happened
    in, and each course to the skills learned in it. Matches that don't resolve
    to a known entity are dropped rather than creating orphan nodes.

## Operational

11. **Supported input formats:** `.pdf`, `.docx`, `.txt`, `.md`. Other files in
    the folder are ignored (logged, not errored).
12. **One Claude call per CV.** CVs are small; batching isn't worth the added
    complexity. Failures on a single CV are recorded in `state["errors"]` and
    the run continues with the rest.
13. **Idempotent writes.** Everything is `MERGE`d, so re-running on the same
    folder updates rather than duplicates.
14. **Secrets and locations live in `.env`** (Neo4j URI/user/password, API keys,
    `CV_FOLDER`, model names). `.env` is git-ignored; `.env.example` is the
    template.
15. **Embeddings are stored as a node property** (`embedding`) and a Neo4j vector
    index is created per labelled node, enabling semantic search later.
