# NyayaRAG From Here: Court-Grade Completion Plan

Read this after:
- `NYAYARAG_MASTER_MEMORY.md`
- `NYAYARAG_EXECUTION_PLAYBOOK.md`
- `NYAYARAG_REVISED_EXECUTION_STRATEGY.md`
- `NYAYARAG_COLLECTION_MASTER_STRATEGY.md`

This document resets the remaining plan from live reality as of `2026-03-31`.

It does not replace the old documents' invariants.
It replaces the remaining execution order and the definition of "done".

The reason for this reset is simple:

`NyayaRAG is not done when it has many documents. NyayaRAG is done only when it is safe to rely on in a real Indian legal matter without silently missing authority, mislabeling authority, or fabricating support.`

## 1. Why A New Plan Is Necessary

The old plans got the architecture right:
- canonical documents,
- provenance,
- appeal-chain validation,
- temporal statute validation,
- placeholder-only citation flow,
- evaluation before trust claims.

But the live state shows a different problem now:
- corpus completion is still materially incomplete,
- several critical collectors are flat or underfilled,
- the current exact-target audit does not cover every corpus family the product itself says is mandatory,
- metadata completeness is not yet being treated as a hard release blocker,
- answer-integrity and evaluation still remain release blockers.

That means the current risk is no longer "wrong architecture".
The current risk is "correct architecture with incomplete reality".

For a legal system, that is dangerous.
One missing authority can change research advice.
One wrong final-authority judgment can flip a cited proposition.
One temporal mistake can apply the wrong law.
One hallucinated citation can destroy trust and directly harm a user's case.

So the new plan must treat all of these as equal blockers:
- missing corpus,
- missing metadata,
- missing lineage,
- missing validity state,
- missing answer-time verification,
- missing evaluation,
- missing operational monitoring.

## 2. Current Reality Snapshot

Source of truth used for this reset:
- `data/collection/EXACT_TARGET_AUDIT.md`
- current `exact_targets.json`
- the existing strategy documents

Audit snapshot at `2026-03-31 13:16:18 UTC`:
- exact-target progress: `4,353,601 / 6,229,412` = `69.9%`
- exact-target gap still missing: `1,875,811`
- total scanned staging documents: `9,061,179`

Largest current exact-target gaps:
- `ITAT`: `316 / 300,000`
- `SC Supreme Court`: `59,129 / 350,000`
- `NCLT`: `270 / 270,000`
- `NCDRC`: `329 / 120,000`
- `CAT`: `2,489 / 100,000`
- `Gazette`: `446 / 50,000`
- `NGT`: `1,295 / 45,000`
- `SEBI`: `702 / 26,000`
- `TDSAT`: `770 / 18,000`
- `NCLAT`: `3,213 / 20,000`
- `RBI`: `123 / 15,000`
- `CBIC`: `1,063 / 12,000`
- `IRDAI`: `91 / 4,500`
- `TRAI`: `2,264 / 6,000`
- `CCI`: `3,544 / 6,000`
- `IBBI`: `480 / 1,300`

Important reality check:
- several High Courts already have real data in staging but are not part of the current exact-target list, including `Gauhati`, `Himachal Pradesh`, `Jharkhand`, `J&K`, `JK Ladakh`, `Manipur`, `Meghalaya`, `Sikkim`, and `Tripura`,
- `law_commission_reports.db` exists in staging but is not part of the current exact-target audit,
- the codebase already contains adapters for `constitution` and `indiacode`, but those corpus families are not currently visible in the exact-target audit.

So `69.9%` is not the same thing as "69.9% of the final NyayaRAG legal universe".
It is only `69.9%` of the currently tracked exact-target slice.

## 3. What The Current Audit Still Misses

The current exact-target registry is not yet the whole court-grade corpus.

The product documents already require these families, but they are not fully represented in the live completion audit:
- Constitution of India
- constitutional amendments
- India Code central acts
- state acts and state amendments
- delegated legislation
- rules
- regulations
- notifications
- circulars
- master directions and master circulars
- office memoranda, schemes, bye-laws, forms, schedules, annexures
- court rules
- practice directions
- Gazette-backed commencement, repeal, substitution, exemption, and supersession records
- district and subordinate case-history subsets through eCourts where public
- Law Commission reports
- parliamentary debates
- committee reports
- parliamentary questions and related legislative history

This means the first correction is not only "finish the current collectors".
The first correction is also:

`make the target registry match the actual product promise.`

## 4. New Definition Of Done

NyayaRAG is complete only when all five gates are complete at the same time.

### Gate 1: Corpus completeness

Complete means:
- every currently registered exact-target source reaches `100%` or `DONE`,
- every mandatory corpus family from the master strategy is present in the target registry,
- every mandatory corpus family has a real source adapter or a declared blocked-state investigation,
- no major tribunal, regulator, constitutional, statute, or delegated-law family is missing from the audit.

### Gate 2: Metadata and provenance completeness

Complete means:
- every record used for verified answers has structured source provenance,
- every record can be traced to source URL and ingestion run,
- every record has enough metadata to support filtering, lineage, and legal confidence labeling,
- metadata completeness is measured source by source and not assumed.

### Gate 3: Authority and validity completeness

Complete means:
- appeal, review, SLP, curative, remand, and stay relationships are modeled where they affect authority,
- overruled, reversed, modified, stayed, repealed, substituted, and superseded materials are correctly marked,
- statute and delegated-law text is time-aware,
- aliases and duplicate citations resolve to one canonical record.

### Gate 4: Answer-integrity completeness

Complete means:
- the model never emits raw legal citations directly,
- placeholders resolve only to canonical documents,
- unsupported claims are labeled unsupported,
- verified claims are actually checked against source support, authority status, and temporal validity,
- the UI exposes why an answer is verified, uncertain, or unsupported.

### Gate 5: Evaluation and operational completeness

Complete means:
- the system has gold fixtures and adversarial tests for Indian legal failure modes,
- collectors are monitored by count growth, not process existence,
- restart verification is mandatory,
- stagnation, duplicate replay, parser drift, and metadata drift are alertable states,
- trust claims are backed by recurring measurements, not intuition.

## 5. Mandatory Metadata Contract

The corpus is not safe if we only store PDFs and text.
The final system must store enough metadata to support retrieval, filtering, legal validation, and user trust.

### 5.1 Core provenance fields

Required for every collected record:
- `doc_id`
- `source_system`
- `source_url`
- `source_document_ref`
- `seed_url`
- `detail_url` when applicable
- `artifact_url` when distinct from the detail page
- `collector_name`
- `collector_run_id`
- `parser_version`
- `collected_at`
- `checksum`
- `mime_type`
- `language`
- `is_ocr`
- `ocr_confidence` when OCR is used

### 5.2 Legal identity fields

Required wherever the source exposes them:
- `doc_type`
- `title`
- `court` or regulator / tribunal name
- `bench`
- `coram`
- `case_number`
- `citation`
- `neutral_citation`
- `parties`
- `decision_date`
- `date_text` when only textual date is available
- `jurisdiction_binding`
- `jurisdiction_persuasive`
- `practice_areas`

### 5.3 Authority and lineage fields

Required wherever applicable:
- `current_validity`
- `overruled_by`
- `overruled_date`
- `appeal_parent_doc_id`
- `appeal_child_doc_id`
- `appeal_outcome`
- `is_final_authority`
- `related_matter_ids`
- `lead_matter_id`
- `batch_group_id`
- `statutes_interpreted`
- `statutes_applied`
- `citation_aliases`

### 5.4 Operational listing fields

Required when discovery happens through listings, feeds, or pagination:
- listing mode
- listing page number or cursor
- result index
- discovered_from feed / sitemap / search / notice / XHR / directory
- session-bound download marker when relevant

### 5.5 Rule

No record is allowed to support a "verified" citation unless the minimum metadata contract is complete enough to explain:
- what it is,
- where it came from,
- why it is authoritative,
- and whether it is current.

## 6. The Missing Things We Must Explicitly Add To The Goal

This section exists to catch "we forgot to count it" failures.

The plan must explicitly include:
- all 25 High Courts, not only the currently targeted subset,
- Supreme Court final judgments and materially relevant orders,
- tribunal families that drive real practice areas,
- regulator instruments that are often the operative law,
- constitutional text plus amendment history,
- central acts plus section histories,
- state acts where officially exposed,
- court rules and practice directions,
- Gazette-backed change records,
- Law Commission and parliamentary materials for reasoning context,
- district / subordinate procedural lineage where text is unavailable but case history is public,
- criminal-code old/new crosswalk quality validation, not only row-count completion,
- multilingual and OCR-heavy documents,
- schedules, annexures, forms, and appended tables that often carry operative legal content.

## 7. New Execution Model: Parallel Blocker Tracks

The old plan was too linear for the current state.
From here, the work must run as parallel blocker tracks.

No single track can declare success on behalf of the whole system.

### Track A: Redefine the audit itself

Deliver:
- `Exact Target Audit v2`
- tiered source registry
- mandatory / optional / support-layer classification
- real done-definition per source family

Must include:
- all 25 High Courts
- currently active tribunal and regulator families
- constitution and amendment layer
- India Code and central-act layer
- state-act layer where official sources exist
- delegated legislation layer
- law-reform and parliamentary support layer

Exit gate:
- there is no major required family that exists in strategy docs but is absent from the audit.

### Track B: Finish the existing exact-target gap

Objective:
- move every currently tracked source to `100%` or `DONE`

Operating rule:
- every restart must be verified by row-count growth after 10 minutes,
- "running but flat" is a failure state,
- repeated underfill escalates to a dedicated adapter,
- source health is judged by count delta plus sampled metadata quality.

Work by collection archetype:
- AWS bulk court collectors
- XHR-paginated listing collectors
- session-bound download collectors
- search-first / hostile portal collectors
- sitemap / RSS / XML directory collectors
- OCR-heavy artifact collectors

Priority order by legal risk and size:
1. SC Supreme Court
2. ITAT
3. NCLT
4. NCDRC
5. CAT
6. Gazette
7. NGT
8. SEBI
9. TDSAT
10. NCLAT
11. RBI
12. CBIC
13. IRDAI
14. TRAI
15. CCI
16. IBBI
17. finish all still-running underfilled sources such as CESTAT, AFT, DRT, SAT, and PFRDA

Exit gate:
- every currently tracked source is complete or has an evidence-backed target revision,
- not one tracked source remains flat without a written root-cause note.

### Track C: Add the missing corpus families

Objective:
- close the gap between the product promise and the target registry

Must add explicit target plans for:
- Constitution and constitutional amendments
- India Code central acts
- state acts
- court rules and practice directions
- Gazette-backed commencement, repeal, supersession, and substitution records
- Law Commission reports
- parliamentary debates and related history material
- district / eCourts lineage subset
- remaining delegated-law families not yet represented

Exit gate:
- audit scope matches the corpus promised by the strategy docs.

### Track D: Metadata and provenance hardening

Objective:
- make every document auditable and safe to use downstream

Deliver:
- one enforced metadata schema,
- source-specific metadata mappers,
- null-rate reporting,
- sampled record audits,
- provenance completeness dashboard,
- backfill jobs for partial records.

Exit gate:
- no verified-answer-eligible record fails the core metadata contract.

### Track E: Authority, lineage, and validity engine completion

Objective:
- make authority resolution legally safe

Must include:
- appeal-family construction
- review / curative / SLP handling
- remand and post-remand linkage
- stay and modification handling
- overruled / reversed / distinguished / followed graph edges
- temporal statute text and amendment propagation
- subordinate-law supersession chains
- citation alias normalization

Exit gate:
- gold fixtures for authority and validity pass cleanly.

### Track F: Answer-integrity completion

Objective:
- prevent hallucinated or unsafe authority display at answer time

Must include:
- placeholder-only generator
- citation resolver
- misgrounding checker
- appeal validator
- temporal validator
- unsupported-claim labeling
- certainty labeling
- source-process transparency in UI/API response shape

Exit gate:
- no answer can surface a verified citation without passing all guards.

### Track G: Evaluation and red-team program

Objective:
- measure the failure modes that matter in Indian legal work

Required benchmark families:
- fabricated citation attempts
- wrong-case same-citation confusion
- same-party different-year confusion
- reversed / modified authority traps
- non-speaking SLP dismissal traps
- post-amendment statute traps
- repeal / supersession traps
- subordinate legislation controlling the outcome while the parent Act alone is insufficient
- batch matter / lead matter confusion
- district-history dependence
- OCR corruption and multilingual extraction failure
- duplicate mirror / duplicate URL / same-PDF-different-URL failure

Exit gate:
- seeded hallucination and authority traps are actually caught before release.

### Track H: Operations, refresh, and monitoring

Objective:
- make completion durable, not one-time

Must include:
- row-count-based watchdogs
- stagnation alerts
- duplicate replay alerts
- parser drift alerts
- lock / timeout visibility
- source freshness cadences
- post-ingest projection refresh
- periodic human audit schedule

Exit gate:
- the corpus can stay complete and trustworthy after backfills finish.

## 8. Edge Cases We Must Not Miss

These are explicit plan items, not nice-to-haves:
- same document reachable from multiple URLs
- same citation string referring to different matters in different courts or years
- interim order incorrectly treated as the final authority
- review or curative judgment altering the apparent finality
- SLP dismissal that does not amount to approval on merits
- remand creating a later controlling judgment
- batch matters where one lead matter controls many tagged matters
- partial overruling rather than full overruling
- statute sections renumbered, substituted, or brought into force later
- notification effective date differing from publication date
- master circular superseding individual circulars
- state amendment overriding the central baseline for a jurisdiction
- schedules, annexures, forms, and tables containing operative law but omitted from chunking
- scanned PDFs returning broken text or HTML masquerading as PDF
- search portals where home-page crawl coverage is false comfort
- hidden pagination revealed only in XHR or first-page metadata
- session cookies or referrer requirements for the actual download link
- bilingual or non-English source pages and PDFs
- OCR confidence too low to support a verified claim
- duplicate re-ingest falsely appearing as progress
- rerun or debug databases being mistaken for canonical completion

## 9. New Immediate Execution Order

This is the order from here.

1. Freeze the definition of release:
   court-grade completeness, not document volume.
2. Build `Exact Target Audit v2` so the audit matches the actual product promise.
3. Finish every currently tracked source to `100%` or `DONE`.
4. Add every missing mandatory source family to the audit with explicit targets and owners.
5. Enforce the metadata contract and backfill incomplete records.
6. Finish authority, lineage, and temporal-validity resolution.
7. Finish the answer-integrity stack.
8. Finish evaluation and adversarial legal red-teaming.
9. Only after all of the above, claim corpus completeness or product trust.

## 10. Court-Grade Release Gates

NyayaRAG must not be described as court-grade unless all of these are true:
- every Tier A mandatory source family is present in the audit and complete,
- every currently tracked exact-target source is at `100%` or `DONE`,
- core metadata completeness is effectively total for verified-answer-eligible documents,
- provenance is traceable for every verified-answer-eligible document,
- appeal and final-authority fixtures pass,
- temporal statute and subordinate-law fixtures pass,
- citation alias resolution passes,
- fabricated citation traps are blocked,
- unsupported-answer labeling works reliably,
- human audits are recurring and logged,
- refresh jobs keep the corpus current without silently regressing completeness.

## 11. Final Operating Rule

From here on, no one should ask only:
- "How many documents do we have?"

The right questions are:
- "What legally important things are still missing?"
- "Which of those are not even in the audit yet?"
- "Can every verified authority be traced, explained, and defended?"
- "Can the system refuse unsafe certainty when the corpus is incomplete?"
- "What failure mode would still embarrass or harm a real lawyer in court?"

That is the right remaining plan.

That is the standard NyayaRAG must meet before it is called complete.
