# SKILL: doc-grounding

Loaded by doc-grounder when grounding a concept from repo-analyst's findings.

## Process

1. Take the concept/pattern name and the file:line reference from
   repo-analyst's finding.
2. Search within the allowlisted domains (config/allowed_doc_sources.yaml)
   -- start with the official API reference/guide, not a blog post, even
   if the blog post is on an allowed domain and ranks better.
3. Fetch the specific page, not just the search result snippet -- the
   citation gate checks against what was actually fetched, and a
   search-result snippet is not the same as retrieved page content.
4. Quote sparingly and paraphrase the rest -- this system produces
   learning material for a human to read, not a copy of the docs.
5. If two allowlisted sources disagree (e.g. a guide and an API reference
   describe the concept differently), report both and let the mismatch
   surface -- do not silently pick one and present it as settled.

## What NOT to do

- Do not fall back to general training knowledge and present it as a
  citation when the allowlist search comes up empty. Say "not found in
  allowlisted sources" explicitly -- see doc_grounder.py's system prompt,
  this is the single most important rule in this subagent's contract.
- Do not fetch outside the allowlist even if you're confident a
  non-allowlisted source (e.g. Stack Overflow, a personal blog) has a
  better explanation. The scoped tool will refuse the fetch anyway, but
  don't attempt to route around it (e.g. via a general-purpose web tool
  if one is mistakenly available in your context).

## Placeholder: framework-specific hints

Fill this in per framework. E.g. for DeepAgents itself:
- Prefer docs.langchain.com/oss/python/deepagents over generic LangChain
  docs when the concept is DeepAgents-specific (permissions, task tool,
  interrupt_on) rather than general LangGraph behavior.
