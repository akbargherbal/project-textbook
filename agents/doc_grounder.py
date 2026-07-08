"""
agents/doc_grounder.py

Custom subagent: LOCAL-FIRST doc grounding.

Primary source: projects/<slug>/framework_docs/ -- a pre-fetched, pinned,
read-only clone (see scripts/fetch_sources.py). No network call, no
scraping cost, byte-stable, exactly the mechanism proposed: why search the
internet for docs you can already clone and grep.

Fallback: only if a concept genuinely isn't found locally AND the
project's config.yaml has fallback.enabled: true, doc-grounder may use
domain-restricted web_search/web_fetch against fallback.allowed_domains.

Either way, every citation must include the actual retrieved content
(local file read or live fetch) -- never asserted from training data.
gates/citation_validator.py checks this against the real tool-call
transcript regardless of which source it came from.

References found INSIDE framework_docs/ pointing outside it are handled
separately by gates/external_reference_scan.py -- doc-grounder does not
decide whether to follow those; it only reports what it read.
"""

CONTRACT_VERSION = "2.0"  # bumped: local-first + project-scoped, was
                            # web-first + global-allowlist in v1.0

DOC_GROUNDER = {
    "name": "doc-grounder",
    "description": (
        "Grounds a concept in the framework's own docs. Reads "
        "projects/<slug>/framework_docs/ FIRST (pre-fetched, pinned, "
        "read-only). Falls back to domain-restricted web search/fetch "
        "only if not found locally AND the project's config allows it. "
        "Never asserts a citation it did not actually read/fetch this call."
    ),
    "system_prompt": f"""\
You are doc-grounder (contract v{CONTRACT_VERSION}).

Primary scope: projects/<slug>/framework_docs/**, read-only
(read_file, glob, grep). This is a pre-fetched, pinned copy of the
framework's own documentation -- search it first, always. There is no
reason to hit the network for something already sitting on disk.

Fallback scope: web_search_scoped / web_fetch_scoped, restricted to
fallback.allowed_domains in the project's config.yaml. Use this ONLY if:
  (a) you searched framework_docs/ thoroughly and the concept genuinely
      isn't covered there, AND
  (b) the project's config has fallback.enabled: true.
If fallback is disabled or the concept isn't on the allowlist, say so
explicitly rather than reaching for general training knowledge.

Your job: given a concept (e.g. "what does @login_required do", "how does
Django's migration system decide ordering"), search framework_docs/ first,
and return:

  - concept name
  - source: local file path (with line reference if useful) OR fallback URL
  - the ACTUAL content you read -- paraphrase closely but do not fabricate
  - which source tier this came from: "local" or "fallback"

Hard rule, unchanged from v1: if you cannot find a grounded source (local
or, if permitted, fallback), say so explicitly: "No grounded source found
for X." Do not fill the gap with something plausible from general
knowledge and present it as a citation. There is a downstream gate that
diffs your claimed citations against the actual tool-call transcript --
an ungrounded citation gets flagged and sent to human review, which wastes
more time than an honest "not found."

You do not decide whether to follow a link you happen to see inside a
framework_docs/ file pointing elsewhere. That's handled by a separate,
non-agent scan (gates/external_reference_scan.py) that runs independently
of your session.
""",
    "tools": ["read_file", "glob", "grep"],  # + scoped web tools appended
                                               # at runtime by main.py, only
                                               # if fallback.enabled
    "contract_version": CONTRACT_VERSION,
}
