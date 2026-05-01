# NyayaRAG Collection Master Strategy

Read this before any large ingestion run, corpus claim, or source-expansion decision.

This file replaces:
- `NYAYARAG_DATA_COLLECTION_BLUEPRINT.md`
- `data/collection/CORPUS_STACK_AND_COLLECTION_ORDER.md`

This is the single master strategy for NyayaRAG corpus design.

This file also absorbs the deeper `Supreme Corpus and Knowledge Architecture` requirements:
- the existing plan is preserved where it is already correct,
- and the modeling depth is raised where court-grade legal reality demands more precision.

It answers:
- what a real Indian lawyer actually studies before court,
- what NyayaRAG must collect to cover that reality,
- how that data must be structured for the architecture already built,
- how to model appeals, reviews, SLPs, remands, batch matters, and legal-change history,
- what can be canonical truth,
- what must stay as secondary or licensed enrichment,
- and what tests must pass before any source is trusted.

## 1. The Core Strategic Conclusion

NyayaRAG does not win by downloading a large number of PDFs.

NyayaRAG wins only if it collects:
- the actual legal authorities a lawyer relies on,
- the procedural lineage that decides whether those authorities still stand,
- the legislative-change layer that decides whether statutory text still stands,
- the alias system that lets every citation resolve to one canonical record,
- and the provenance trail that makes the corpus auditable.

The correct corpus target is therefore:

`Documents + lineage + validity + aliases + provenance + retrieval projections`

Not just documents.

## 2. Reality Check: What Judges And Lawyers Actually Use

The safest way to design the NyayaRAG corpus is to look at how serious legal libraries are built in India and what publisher catalogs show lawyers actually buy and use.

### 2.1 Official library reality

The official [Supreme Court Judges Library page](https://www.sci.gov.in/judges-library/) publicly describes its holdings as including:
- law reports,
- statutes,
- commission and committee reports,
- state legislation,
- parliamentary debates,
- other legislative materials,
- journals,
- and complete documentation of acts, amendments, rules, regulations, bye-laws, schemes, and notifications.

That is an important reality check.

A judge-facing research system in India cannot stop at:
- judgments,
- and a few bare acts.

It must include:
- law reports,
- statutes,
- delegated legislation,
- legislative materials,
- law reform reports,
- and procedural history.

### 2.2 Official parliamentary and law-reform reality

The official [Parliament Digital Library](https://eparlib.sansad.in/about_us.jsp) exposes:
- debate proceedings,
- historical debates,
- parliamentary questions and answers,
- committee reports,
- bulletins,
- and other parliamentary publications.

The official [Law Commission of India](https://lawcommissionofindia.nic.in/documents/) exposes report-numbered law reform material across major subject areas.

This matters because a real constitutional or statutory lawyer often studies:
- the text,
- the amendment,
- the judicial interpretation,
- and the law-reform / legislative background.

### 2.3 Official legislative reality

The official [India Code](https://www.indiacode.nic.in/) and [Legislative Department](https://lddashboard.legislative.gov.in/documents/list-of-central-acts) surfaces show that the statute layer is not only “Act text.”

It includes:
- act listings,
- regional-language versions of important central acts,
- year-wise lists,
- amendment history,
- and related legislative materials.

NyayaRAG must therefore treat legislation as:
- a changing tree,
- not a flat text blob.

### 2.4 District and case-status reality

The official [eCourts Services information page](https://services.ecourts.gov.in/App/appaboutus.html) makes clear that district and taluka court systems expose:
- CNR,
- case status,
- hearing history,
- cause lists,
- and stakeholder-facing procedural information.

This is critical because:
- lower-court text availability is uneven,
- but procedural history is often available and legally important.

### 2.5 Real lawyer shelf reality

Publisher catalogs strongly confirm that Indian legal research is built on layered material, not one source type.

Examples visible on current legal-book and legal-database catalogs include:
- D D Basu on the Constitution
- M P Jain on Indian Constitutional Law
- Justice G P Singh on Principles of Statutory Interpretation
- Ratanlal & Dhirajlal on the Criminal Procedure Code and the Indian Penal Code
- Mulla on the Code of Civil Procedure
- Kanga & Palkhivala on Income Tax
- Halsbury’s Laws of India volumes
- Universal / Lexis / EBC bare-act and central-acts compilations

Representative source references used for this plan:
- [Lexis title-list PDF with D D Basu, M P Jain, and related constitutional titles](https://store.lexisnexis.in/catalog/view/theme/lexisnexis/image/LK_SMP_TitleList_new.pdf)
- [Lexis price-list PDF showing bare acts, commentaries, and subject sets](https://store.lexisnexis.in/PriceList.pdf)
- [EBC Webstore home and catalog entry point](https://www.ebcwebstore.com/)

These references do not mean NyayaRAG must ingest proprietary material immediately.

They mean the corpus design must leave room for:
- reporters,
- commentaries,
- encyclopedic sets,
- subject treatises,
- and edition-aware bare acts.

## 3. The Lawyer Study Stack

A real Indian lawyer preparing to stand before a judge studies a stack of materials in descending order of authority and practical utility.

NyayaRAG must mirror that stack.

### 3.1 Constitutional and foundational layer
- Constitution of India
- constitutional amendments
- schedules
- constituent assembly material
- Constitution Bench judgments
- leading federalism / rights / separation-of-powers jurisprudence

### 3.2 Primary statutory layer
- central acts
- state acts
- criminal-code transition layer: IPC / CrPC / Evidence Act + BNS / BNSS / BSA
- schedules, appendices, forms, annexures
- state amendments where legally relevant

### 3.3 Delegated and subordinate law layer
- rules
- regulations
- notifications
- circulars
- office memoranda
- schemes
- bye-laws
- practice directions
- court rules
- master directions / master circulars

This layer is not optional.

In many practice areas, the actual operative law is here.

### 3.4 Binding and persuasive case-law layer
- Supreme Court
- jurisdiction-relevant High Court
- other High Courts as persuasive authorities
- tribunals and commissions that produce the operative jurisprudence
- district and subordinate case history where it affects lineage, fact pattern, or procedural posture

### 3.5 Procedural and appellate lineage layer
- trial history
- appeal history
- review history
- curative history
- SLP history
- remands
- stays
- transfers
- clubbed and batch matters
- lead-matter relationships

Without this layer, NyayaRAG will surface authorities that look right but are not safe to cite.

### 3.6 Research-support layer
- Law Commission reports
- standing committee reports
- parliamentary debates
- legislative history material
- doctrinal summaries
- public legal manuals where licensing permits

### 3.7 Reporter and commentary layer
- SCC
- AIR
- SCR
- subject reporters
- act commentaries
- subject treatises
- practice manuals
- legal encyclopedias
- journals and digests

This layer is commercially important, but it is not canonical truth.

### 3.8 Private matter layer
- user uploads
- pleadings
- prior orders
- FIR / charge sheet / complaint
- contracts
- evidence bundles
- chamber or firm knowledge banks if later enabled

This layer is essential for document-specific research, but must never be merged into public canonical law.

## 4. The Correct Corpus Layering Model

NyayaRAG should maintain four public/private corpus layers with strict separation.

## 4.1 Layer A: Canonical public law

This is the truth layer.

Includes:
- Supreme Court judgments and material orders
- High Court judgments and important orders
- tribunal and commission judgments/orders
- district/subordinate judgments/orders where available
- Constitution
- constitutional amendments
- central acts
- state acts
- subordinate legislation
- court rules
- practice directions
- regulator instruments
- gazette-backed legal-change records

Rule:
- only this layer can directly support verified legal propositions as canonical law.

## 4.2 Layer B: Public secondary and interpretive support

Includes:
- Law Commission reports
- standing committee reports
- parliamentary debates
- constituent assembly debates
- public reports from courts and institutions
- public legal manuals or structured explainers where copyright permits

Rule:
- these can support routing, doctrine explanation, and context,
- but cannot override or replace primary law.

## 4.3 Layer C: Licensed enrichment

Includes:
- reporters
- commentaries
- encyclopedic sets
- manuals
- treatises
- digest systems
- proprietary headnotes

Rule:
- this layer must be edition-aware and license-aware,
- and must remain separate from canonical primary-law objects.

## 4.4 Layer D: Private workspace corpus

Includes:
- case papers
- uploaded files
- firm notes if later enabled
- saved workspace outputs and matter records

Rule:
- private matter material can influence retrieval for the user’s case,
- but it is never public-law truth.

## 5. What NyayaRAG Must Collect 100%

If NyayaRAG wants court-grade trust, these public-law families are mandatory.

## 5.1 Courts and adjudicatory bodies

Mandatory:
- Supreme Court judgments
- Supreme Court materially relevant orders
- all High Court judgments
- significant High Court interim or procedural orders where they affect the present legal position
- district and subordinate orders/judgments where accessible
- tribunal and commission orders in major domains

Priority tribunal and commission families:
- NCLT
- NCLAT
- ITAT
- CAT
- NGT
- SAT
- TDSAT
- CESTAT
- APTEL
- NCDRC
- DRT / DRAT
- Armed Forces Tribunal
- Competition Commission adjudicatory material where public

## 5.2 Constitution and statutes

Mandatory:
- Constitution of India
- all constitutional amendments
- all unrepealed central acts
- state acts
- BNS / BNSS / BSA
- old criminal codes and transition equivalents

## 5.3 Delegated and subordinate legislation

Mandatory:
- rules
- regulations
- notifications
- circulars
- schemes
- bye-laws
- ordinances
- prescribed forms
- office memoranda where legally operative
- court rules
- practice directions

## 5.4 Legal-change and freshness layer

Mandatory:
- amendment acts
- commencement notifications
- repeal notifications
- rescission / supersession notifications
- replacement instruments
- state amendment events
- court-rule changes

Without this layer, the validity engine cannot stay correct.

## 5.5 Regulator and departmental law layer

Mandatory for practical legal coverage:
- SEBI regulations, circulars, master circulars
- RBI master directions, notifications, circulars
- MCA rules and company-law delegated legislation
- IBBI regulations and circulars
- CBIC notifications, circulars, instructions
- CBDT circulars, rules, forms, finance-act-linked updates
- IRDAI regulations and circulars
- PFRDA regulations
- TRAI regulations / directions
- Competition Commission regulations and orders
- labour / EPFO / ESIC notifications and schemes
- environmental notifications and delegated instruments

## 6. “Everything A Lawyer Reads” Properly Understood

The phrase is correct in spirit but must be modeled correctly.

“Everything a lawyer reads” does not mean:
- scrape all books into one blob,
- or mix commentaries into primary law.

It means NyayaRAG must be able to represent these object classes:

### 6.1 Bare-act layer
- updated bare acts
- central bare acts
- state bare acts
- criminal-code crosswalks
- allied rules, forms, schedules

### 6.2 Reporter layer
- SCC
- AIR
- SCR
- subject reporters in tax, company, labour, criminal, arbitration, consumer, service law, and similar domains

### 6.3 Commentary layer
- constitutional commentary
- statute-specific commentary
- procedural commentary
- tax commentary
- company / insolvency commentary

### 6.4 Treatise and manual layer
- constitutional law treatises
- statutory interpretation works
- criminal practice manuals
- civil procedure manuals
- drafting and pleading manuals
- subject-area manuals

### 6.5 Legal encyclopedia / digest layer
- Halsbury-type subject overviews
- digest systems
- topic maps and headnote systems

### 6.6 Journal layer
- law review and bar-journal material
- current-awareness publications
- focused case-note material

### 6.7 Example shelf that NyayaRAG must leave room for

Representative example families visible in current catalogs:
- D D Basu on the Constitution
- M P Jain on Constitutional Law
- Justice G P Singh on Statutory Interpretation
- Ratanlal & Dhirajlal on criminal law/procedure
- Mulla on civil procedure
- Kanga & Palkhivala on Income Tax
- Halsbury’s Laws of India subject volumes
- Universal’s updated central acts and rules sets

Design rule:
- these are a future enrichment layer unless properly licensed,
- but the corpus schema must support them from day one.

## 7. What To Avoid Treating As Canonical Truth

Do not treat any of the following as authoritative public law:
- blogs
- legal news stories
- unofficial AI summaries
- social-media explainers
- user-generated headnotes
- community wiki notes
- unsourced legal coaching notes
- forum posts

They may be discoverability aids later, but not verified legal sources.

## 8. The Canonical Public-Law Objects That Must Exist

For the architecture already built, PostgreSQL must contain these canonical objects.

## 8.1 Judgment / order record

Each judgment/order must have:
- `doc_id`
- canonical title
- case numbers
- party names
- neutral citation if available
- reporter alias citations if available
- court
- bench / coram
- bench size
- date decided
- reserved date if available
- reportable / unreportable flag if available
- raw artifact references
- normalized text with page and paragraph anchors
- disposition / outcome
- language
- provenance

## 8.2 Statute / instrument record

Each Act/instrument must have:
- `doc_id`
- act name
- short title
- act number
- year
- enactment date
- commencement date
- jurisdiction
- ministry/department
- repeal/replacement status
- amendment history
- subordinate legislation links
- provenance

## 8.3 Section record

Each section must have:
- section number
- heading
- current text
- prior text snapshots where amended
- effective dates
- in-force status
- schedules/forms linkage if relevant
- crosswalk links for criminal-code transitions
- interpreting-case links

## 8.4 Proceeding family record

Each litigation family must have:
- `proceeding_family_id`
- originating matter references
- trial / appellate / review / curative / SLP members
- batch and lead-case relationships
- transfer / renumbering history
- final-authority computation

## 8.5 Citation alias record

Each authority must support alias resolution through:
- neutral citation
- reporter citations
- official case number
- party-title variants
- source-specific identifiers

## 8.6 Legal-change record

Each legal-change event must capture:
- amendment
- commencement
- repeal
- rescission
- substitution
- supersession
- court-rule change
- regulator circular update

## 9. What Must Never Be Flattened

The collection program must not flatten away the relationships that make law usable.

Never flatten:
- a statute into one current-text blob without amendment history
- a judgment family into one “latest case” reference
- multiple aliases into multiple authorities
- a lead matter and connected matters into unrelated records
- a regulator circular into only the parent Act
- a review/SLP/remand/stay chain into one final flag
- commentary text into canonical truth

If this flattening happens, NyayaRAG will still look technically polished while giving legally unsafe answers.

## 10. Real-World Appellate And Procedural Reality

The user’s intuition is correct:
- if a lower judgment is challenged and displaced later, the lower judgment may no longer be safe as present authority.

But the model must be more precise than:
- “old case wrong / new case right.”

## 10.1 Proceeding states NyayaRAG must model

Mandatory states:
- affirmed
- reversed
- modified
- remanded
- partly allowed
- dismissed on merits
- dismissed for delay
- dismissed for default
- dismissed for maintainability
- review dismissed
- review allowed
- curative dismissed
- SLP pending
- SLP dismissed non-speaking
- SLP granted and later decided
- referred to larger bench
- stayed
- transferred
- batch/clubbed
- renumbered

## 10.2 Precedential effect states NyayaRAG must compute

Mandatory validity states:
- `GOOD_LAW`
- `OVERRULED`
- `PARTLY_OVERRULED`
- `MODIFIED_ON_APPEAL`
- `REMANDED_PENDING`
- `STAYED_OPERATION`
- `REFERRED_TO_LARGER_BENCH`
- `REVIEW_PENDING`
- `CURATIVE_PENDING`
- `SLP_PENDING`
- `SLP_DISMISSED_NON_SPEAKING`
- `DISTINGUISHED`
- `DOUBTED`

## 10.3 Important legal nuances

NyayaRAG must account for these realities:
- a non-speaking SLP dismissal does not automatically convert the lower-court judgment into Supreme Court-approved law
- a remand means the matter is not finally settled in the ordinary way
- a stay can suspend operation without erasing history
- a larger-bench reference weakens reliance even before final resolution
- a partly-overruled judgment may remain good on one point and dead on another
- connected batch matters may make the lead case the real controlling authority

## 10.4 Graph edges NyayaRAG must maintain

At minimum:
- `CITES`
- `INTERPRETS`
- `APPLIES`
- `APPEAL_FROM`
- `AFFIRMED_BY`
- `REVERSED_BY`
- `MODIFIED_BY`
- `REMANDED_TO`
- `REVIEW_OF`
- `CURATIVE_OF`
- `REFERRED_TO_LARGER_BENCH`
- `BATCHED_WITH`
- `TRANSFERRED_FROM`
- `STAYED_BY`
- `PART_OF_DOCTRINE`

## 11. Source-By-Source Collection Program

NyayaRAG should collect from official or institutionally authoritative sources first, then use licensed/commercial sources as enrichment later.

## 11.1 Supreme Court

Primary sources:
- [Supreme Court of India](https://www.sci.gov.in/)
- official Supreme Court PDFs and search/index surfaces
- Supreme Court reports/search surfaces where officially exposed
- NJDG-linked Supreme Court data where useful for metadata/context

Collect:
- judgments
- relevant orders
- case numbers
- bench
- neutral citations where present
- connected matters where discoverable

## 11.2 High Courts

Primary sources:
- official websites of each High Court

Reality:
- metadata schemas vary sharply,
- search patterns vary,
- URLs and pagination can be unstable,
- artifact quality varies.

Strategy:
- one adapter family per High Court pattern,
- court-specific metadata overrides,
- strict provenance and replay logs,
- duplicate collapse across mirrors.

## 11.3 District and subordinate courts

Primary sources:
- [eCourts Services](https://services.ecourts.gov.in/App/appaboutus.html)
- NJDG where appropriate for public data
- linked district judgments/orders where public

Collect:
- CNR
- party names
- advocate names where public
- case status
- hearing history
- order/judgment links
- transfer and proceeding history

Reality:
- text availability is uneven,
- but procedural history is often rich and useful.

## 11.4 Statutes and constitutional material

Primary sources:
- [India Code](https://www.indiacode.nic.in/)
- [Legislative Department central acts lists](https://lddashboard.legislative.gov.in/documents/list-of-central-acts)
- [regional-language central acts listing](https://lddashboard.legislative.gov.in/regional-language)

Collect:
- Constitution
- constitutional amendments
- central acts
- state acts where officially exposed
- section trees
- schedules and forms
- state amendments where relevant
- regional-language parallel texts where officially available

## 11.5 Gazette and legal-change layer

Primary sources:
- Gazette-backed legal notifications and amendment publications
- legislative department updates

Collect:
- amendment acts
- commencement notifications
- repeal notifications
- substituted rules
- supersession events
- court-rule amendments
- regulator update events

## 11.6 Parliamentary and law-reform layer

Primary sources:
- [Parliament Digital Library](https://eparlib.sansad.in/)
- [Law Commission of India](https://lawcommissionofindia.nic.in/documents/)

Collect:
- debates
- historical debates
- committee reports
- questions/answers if later useful
- law commission reports
- legislative background references

Label this layer:
- `secondary`
- `non_binding`
- `contextual`

## 11.7 Regulators and departments

Primary sources:
- [SEBI](https://www.sebi.gov.in/)
- [RBI](https://www.rbi.org.in/)
- [IBBI](https://www.ibbi.gov.in/)
- [CCI](https://www.cci.gov.in/)
- plus other equivalent official regulator sites

Collect:
- regulations
- circulars
- master directions / master circulars
- rules and amendment notifications
- enforcement/adjudication orders where public
- FAQs only as `secondary/contextual`

## 11.8 Licensed books, reports, and reporter systems

Commercial source families for later stages:
- SCC
- AIR
- SCR where licensed / usable
- Lexis packages
- Universal sets
- EBC products
- subject reporters
- commentaries
- encyclopedias
- manuals

Rule:
- these are future enrichment unless licensed and integrated properly.

## 12. Canonical Packaging Standard

Each collected public-law document must be stored as a package of layers, not a single blob.

## 12.1 Raw artifact layer
- original PDF / HTML / XML / scan
- checksum
- source URL
- fetch timestamp
- fetch headers / content-type where useful

## 12.2 Canonical record layer
- stable `doc_id`
- canonical metadata
- aliases
- provenance

## 12.3 Normalized text layer
- page-aware text
- paragraph-aware text
- section-aware text where applicable
- OCR confidence and page map for scans

## 12.4 Relationship layer
- citation edges
- appeal/proceeding edges
- statute-interpretation links
- connected-matter links

## 12.5 Retrieval layer
- legal chunks
- lexical search docs
- vector payloads
- graph projections

## 12.6 Freshness and validity layer
- amendment state
- repeal/replacement state
- appeal-state changes
- stay state
- re-embedding triggers
- re-index triggers

## 13. Canonical Identity Rules

Identity must never depend only on a raw citation string.

Use:
- `doc_id` as canonical identity
- `proceeding_family_id` as litigation-lineage identity
- alias tables for citation and title variants

Each judgment must support:
- neutral citation
- reporter citations
- official case numbers
- party-title variants
- source-specific ids

Each statute must support:
- act id
- act number + year
- short title
- common abbreviation
- section aliases
- criminal-code equivalence mapping where relevant

## 14. Collection Order For NyayaRAG

The order matters because the architecture is already built around:
- validity,
- appeal chains,
- citation resolution,
- graph projection,
- and benchmark gates.

## 14.1 Order 0: Gold truth set first

Before mass ingestion, build the gold truth set:
- appellate fixtures
- amendment/repeal fixtures
- alias/duplicate fixtures
- doctrine-chain fixtures
- district-history fixtures
- tribunal-history fixtures

Purpose:
- prove the collectors,
- not merely the scrapers.

## 14.2 Order 1: National core

Collect first:
- Constitution
- constitutional amendments
- India Code central acts
- criminal-code transition corpus
- Supreme Court judgments and key orders

Purpose:
- establish the national citation and validity backbone.

## 14.3 Order 2: Core case-law expansion

Collect next:
- 3 representative High Court families
- one district-history subset via eCourts
- 3 major tribunals

Purpose:
- prove adapter diversity,
- prove appellate/procedural linkage under real source variance.

## 14.4 Order 3: Full High Court and tribunal program

Collect:
- all High Courts
- all major tribunals and commissions
- linked subordinate history where practical

Purpose:
- make jurisdictional retrieval credible.

## 14.5 Order 4: Subordinate legislation and regulator layer

Collect:
- rules
- regulations
- circulars
- notifications
- court rules
- practice directions
- regulator instruments

Purpose:
- make statutory answers operationally correct.

## 14.6 Order 5: Public secondary support

Collect:
- Law Commission
- parliamentary materials
- debates
- committee reports
- doctrinal summaries and public institutional material

Purpose:
- improve doctrine tracing, explanation, and routing.

## 14.7 Order 6: Licensed enrichment

Collect only after:
- licensing is real,
- storage/use rights are clear,
- edition-aware modeling is ready.

## 14.8 Order 7: Private workspace corpora

Continue expanding:
- uploads
- matter packs
- saved workspaces
- firm/chamber material if later enabled

But keep them separate from public canonical law.

## 15. Source Approval Registry

No source should become “production” just because a scraper returns files.

Every source must have a registry record like [source_registry_template.yaml](/Users/mohanganesh/project002/data/collection/source_registry_template.yaml) covering:
- source id
- institution owner
- legal status: official / licensed / contextual only
- document families
- jurisdiction coverage
- date coverage
- artifact types
- incremental strategy
- backfill strategy
- retry and rate-limit policy
- duplicate-collapse strategy
- alias fields
- proceeding keys
- freshness SLA
- quality gates
- operator notes

## 16. Freshness And Update Cadence

Not every source should run on the same schedule.

Suggested default cadence:
- Supreme Court latest docs: daily
- high-volume High Courts: daily or twice daily
- other High Courts: daily
- tribunals: daily
- eCourts tracked matters: daily
- eCourts broad backfill: weekly
- India Code and legislative diff checks: daily
- gazette and legal-change feeds: daily
- regulator circular/notification checks: daily
- Law Commission / parliamentary / public secondary: weekly
- licensed commentary editions: manual or release-triggered

Operational rule:
- latest layers must be incremental,
- older layers may backfill in slower windows,
- every refresh must be idempotent.

## 17. The Non-Negotiable Test Program

Collection is not trusted because the fetch completed.

A source is trusted only if it passes:
- metadata completeness
- artifact integrity
- duplicate collapse
- citation extraction precision
- citation extraction recall
- proceeding-family linkage accuracy
- appeal-chain accuracy
- final-authority accuracy
- temporal-validity accuracy
- amendment propagation accuracy
- chunk-boundary correctness
- section-level retrieval accuracy
- case-specific retrieval accuracy
- doctrine-chain completeness
- district-history linkage accuracy

## 17.1 Human audits

Minimum recurring audits:
- 50 random Supreme Court docs
- 50 random High Court docs
- 25 district-history matters
- 25 tribunal matters
- 50 statute sections
- 25 amendment/repeal chains
- 25 appeal-chain families

## 17.2 Gold fixture matrix

The gold fixture matrix remains in:
- [GOLD_FIXTURE_MATRIX.md](/Users/mohanganesh/project002/data/collection/GOLD_FIXTURE_MATRIX.md)

It must include:
- straight affirm/reverse/modify/remand patterns
- review and curative patterns
- SLP non-speaking dismissal and granted-SLP patterns
- batch matters
- transfers and renumbering
- partial overruling
- repeal and amendment chains
- criminal-code transitions
- duplicate mirrors
- citation aliases

## 18. Go / No-Go Rules

Do not claim `complete Indian corpus` until:
- national core sources are ingested,
- all target High Courts are represented,
- major tribunal families are represented,
- core statutes and criminal-code transitions are live,
- appeal/final-authority accuracy passes the gold set,
- validity and amendment updates are running correctly,
- retrieval projections are refreshed and benchmarked.

Do not claim `everything a lawyer reads` until:
- the licensed reporter/commentary layer is actually licensed and integrated,
- not merely anticipated.

## 19. The Final Design Rule

If NyayaRAG wants to be safe enough for judge-facing legal work, the collection system must keep these together:
- law text
- case text
- citation graph
- appeal/proceeding lineage
- amendment/repeal/change history
- alias system
- provenance

If even one of those is weak, the answer can look convincing while still being wrong in a court-facing sense.

That is why corpus design is the real moat.

## 20. Review Of The Existing Plan

## 20.1 What the existing plan gets right

These existing NyayaRAG decisions remain correct and must not be weakened:
- canonical `doc_id` identity
- proceeding-family architecture
- citation alias system
- source provenance
- validity engine
- appeal-chain modeling
- layered corpus separation
- graph-aware retrieval
- zero-hallucination verification path

The earlier plan was already right about one foundational truth:

`A legal corpus is not a pile of PDFs.`

It is a structured authority system.

## 20.2 What this master strategy adds

This strategy goes beyond “what to collect” and specifies:
- the full adjudicatory universe NyayaRAG must know
- the complete appeal-path map
- the deeper statutory and legislative tree
- the practice-area knowledge map
- the commentary/reference-text universe
- the full metadata field inventory
- the complete graph relationship set
- the freshness cascade rules
- and the gold-truth fixtures required for production trust

## 21. Complete Indian Court And Adjudicatory Universe

NyayaRAG must model every forum in India that produces legally operative output a lawyer may cite.

If a forum issues:
- judgment
- order
- award
- direction
- ruling
- determination
- circular
- notification
- or quasi-judicial decision

it belongs in the NyayaRAG knowledge universe.

## 21.1 Supreme Court of India

The Supreme Court must not be modeled as one undifferentiated stream of PDFs.

Distinct output families:
- Constitution Bench judgments
- regular division-bench judgments
- single-judge procedural orders where institutionally relevant
- Article 32 original-writ matters
- Special Leave Petition admission-stage orders
- speaking dismissals of SLPs
- non-speaking dismissals of SLPs
- granted SLPs that convert into civil or criminal appeals
- review petitions
- curative petitions
- Article 143 Presidential References
- suo motu matters
- contempt proceedings
- reference orders to larger benches

Critical rule:
- `SLP_DISMISSED_NON_SPEAKING` must never be treated as Supreme Court approval of the lower-court ratio.

Critical metadata:
- bench composition
- bench size
- Constitution Bench flag
- reference-to-larger-bench flag
- speaking vs non-speaking dismissal
- admitted-SLP vs rejected-SLP lifecycle stage

## 21.2 High Courts

All 25 High Courts must be modeled individually, not as a generic `High Court` bucket.

Each High Court record family must preserve:
- court identity
- state/territorial jurisdiction
- principal seat
- bench/seat metadata
- original-side vs appellate-side distinction where applicable
- single-bench / division-bench / full-bench authority
- Letters Patent / intra-court appeal context where relevant

Practical rule:
- a High Court judgment is binding only within its jurisdiction unless a higher authority controls,
- outside that jurisdiction it is persuasive only.

Important intra-High-Court structures:
- single bench
- division bench
- full bench
- larger bench reference within the same High Court
- original side civil jurisdiction in courts such as Bombay, Calcutta, Madras, and Delhi

Important seat-level reality:
- benches such as Lucknow, Nagpur, Aurangabad, Madurai, Jaipur and similar seats are not separate courts,
- but seat metadata still matters for case-number parsing and source provenance.

## 21.3 District and subordinate courts

This is the real litigation universe of India and must not be treated as optional.

Collect and model:
- District and Sessions Courts
- Additional District Judge courts
- Civil Judge Senior Division
- Civil Judge Junior Division / Munsif variants
- Chief Judicial Magistrate / ACJM / JMFC structures
- Family Courts
- Commercial Courts
- Small Causes Courts
- Motor Accident Claims Tribunals
- Rent Controllers / Rent Courts
- Juvenile Justice Boards where relevant
- other state-specific subordinate forums

What matters most here is often:
- CNR
- case status
- hearing history
- order history
- transfer history
- disposal type
- linked uploaded orders/judgments where public

Rule:
- district-court metadata and lineage are often more valuable than one isolated PDF.

## 21.4 Tribunal and commission universe

NyayaRAG must model the major Indian tribunal ecosystem as first-class jurisprudential layers, not side folders.

Mandatory families:
- NCLT
- NCLAT
- ITAT
- CESTAT
- CAT
- NGT
- SAT
- APTEL
- TDSAT
- DRT / DRAT
- NCDRC + state and district consumer structure
- Armed Forces Tribunal
- RERA Authorities and Appellate Tribunals
- Competition Commission adjudicatory orders and appeal path
- Information Commissions
- Labour Courts and Industrial Tribunals
- Railway Claims Tribunal
- Revenue / Board of Revenue structures where public
- Waqf Tribunals
- cooperative and state-specialized tribunals where legally operative

Critical rule:
- each tribunal family must carry its own appeal path, bench/seat metadata, case-number conventions, and statutory basis.

## 21.5 Special and designated courts

NyayaRAG must also recognize special-court families because they matter procedurally and doctrinally:
- NDPS courts
- POCSO / FTSC structures
- Prevention of Corruption special courts
- NIA / UAPA courts
- PMLA courts
- CBI special courts
- Commercial Courts
- Family Courts
- Lok Adalats / Permanent Lok Adalats
- Courts Martial

These are not always separate “higher precedential” bodies, but they are crucial for:
- procedure
- appeal path
- and case-type-specific retrieval.

## 22. Complete Appeal Chain Universe

If NyayaRAG cannot model the full appeal path of a matter, it cannot safely claim final-authority awareness.

## 22.1 Standard civil path

Model:
- trial court decree
- first appeal
- second appeal where applicable
- High Court
- Supreme Court via certificate or Article 136

Important:
- each stage is a separate authority object,
- and the final authority is the last merits-stage decision, not merely the most recent filed proceeding.

## 22.2 Standard criminal path

Model:
- investigation
- magistrate cognizance / committal where relevant
- Sessions trial
- High Court appeal or revision
- Supreme Court appeal / SLP

Critical nuance:
- acquittal appeals
- revisions
- bail-stage precedent
- custody / default-bail timing

must all be represented separately.

## 22.3 Writ and intra-court path

Model:
- Article 226 single-bench judgment
- intra-court appeal / Letters Patent Appeal
- division-bench decision
- full-bench reference where applicable
- Supreme Court SLP / appeal

Critical rule:
- division-bench output supersedes conflicting single-bench output within the same High Court.

## 22.4 Tribunal appeal matrix

NyayaRAG must encode tribunal-family-specific appeal paths, including examples such as:
- NCLT -> NCLAT -> Supreme Court
- ITAT -> High Court -> Supreme Court
- CESTAT -> High Court / Supreme Court depending on statute and issue
- CAT -> High Court -> Supreme Court
- NGT -> Supreme Court
- SAT -> Supreme Court
- APTEL -> Supreme Court
- TDSAT -> Supreme Court
- DRT -> DRAT -> High Court -> Supreme Court
- AFT -> Supreme Court
- District Consumer -> State Commission -> NCDRC -> Supreme Court
- CCI historical and current appeal path transitions
- RERA Authority -> RERA Appellate Tribunal -> High Court -> Supreme Court

These paths must be typed graph relationships, not loose text notes.

## 22.5 SLP lifecycle

The SLP lifecycle must be tracked stage by stage:
- filed
- notice / admission-stage development
- dismissed non-speaking
- dismissed speaking
- leave granted
- converted to appeal
- decided on merits
- review filed
- review dismissed / allowed
- curative filed
- curative dismissed / allowed

The validity engine must understand the difference between these states.

## 22.6 Batch matters

Batch matters require:
- `LEAD_CASE_FOR`
- `CONNECTED_MATTER_OF`
- short disposal orders that merely say “disposed of in terms of”
- and retrieval logic that returns the lead matter as the substantive authority

## 22.7 Remand

Remand must not be simplified into a generic “modified” state.

NyayaRAG must understand:
- original judgment set aside
- remanding legal directions
- post-remand lower-court judgment if later issued
- and possible re-appeal after remand

## 23. Complete Statutory And Legislative Universe

## 23.1 Statutes are trees, not flat text

An Act must be modeled as:
- Act
- chapter/part hierarchy where present
- section tree
- sub-section / clause / proviso / explanation structure
- schedules
- forms
- appendices
- amendment history
- commencement history
- repeal/replacement history

## 23.2 Central statute universe

Ultimately every unrepealed central act should exist in the corpus at least as a metadata object.

Deep-model priority families include:
- constitutional law corpus
- criminal law corpus
- civil procedure and evidence corpus
- contract/property/specific relief corpus
- companies / insolvency corpus
- tax corpus
- environmental corpus
- personal law corpus
- arbitration corpus
- IP corpus
- technology / telecom / privacy corpus
- banking / securities / competition corpus

## 23.3 State-statute universe

NyayaRAG must explicitly plan for state-specific acts in areas such as:
- tenancy
- land reform
- cooperative societies
- shops and establishments
- stamp and registration
- municipal law
- revenue law
- police and excise
- state service and local-government law

Concurrent-list and presidential-assent conflicts must be understood as a legal-reality problem, not ignored.

## 23.4 Criminal-code transition universe

The IPC -> BNS, CrPC -> BNSS, and IEA -> BSA transition is a dedicated sub-corpus, not a small mapping table.

The system must know:
- old section
- new section
- whether the mapping is direct, modified, split, merged, or missing
- offence-date sensitivity
- pre-July-2024 vs post-July-2024 applicability

Retrieval rule:
- criminal queries must automatically search both old and new regimes when the law is substantively continuous.

## 23.5 Subordinate legislation universe

This is one of the most neglected layers in legal AI and must be treated as mandatory.

Collect and model:
- statutory rules
- regulations
- master directions
- master circulars
- notifications
- exemption notifications
- office memoranda
- guidance documents with legal effect where applicable
- court rules
- practice directions

Critical rule:
- supersession and replacement must be modeled explicitly,
- especially for RBI, SEBI, GST, customs, and similar regimes.

## 23.6 Constitutional amendments as first-class objects

Each constitutional amendment must be stored as a dedicated object with:
- amendment number
- date of enactment
- date of commencement
- provisions inserted/substituted/omitted
- linked constitutional articles
- linked challenge judgments
- current constitutional-validity status if challenged

## 24. Complete Knowledge Domain Map

Each practice area must have:
- practice-area tags
- dedicated doctrine clusters
- specialized metadata filters
- and retrieval ranking logic adapted to that domain

Minimum deep domains:
- constitutional law
- criminal law
- civil procedure and litigation
- company law and insolvency
- tax law
- labour and service law
- property / land / real estate law
- family and personal law
- arbitration and ADR
- intellectual property
- environmental law
- administrative law and judicial review

Important product rule:
- each domain must know both its primary authorities and its domain-specific subordinate/regulatory layers.

## 25. Standard Legal Texts And Commentary Universe

These are not canonical law objects unless licensed and ingested, but they are part of the real lawyer research universe and the schema must leave room for them.

Representative reference families that NyayaRAG must be able to model as Layer C enrichment:
- D D Basu
- M P Jain
- H M Seervai
- V N Shukla
- G P Singh
- Ratanlal & Dhirajlal
- Woodroffe and Amir Ali
- Mulla
- Sarkar
- Pollock & Mulla
- Kanga & Palkhivala
- Chaturvedi & Pithisaria
- Halsbury’s Laws of India
- subject digests and annual digests

Modeling rule:
- edition-aware
- page-anchor-aware
- publisher-aware
- clearly separated from primary law

## 26. Metadata Architecture At Maximum Precision

The earlier sections define the canonical objects. This section raises the minimum required fields for production use.

## 26.1 Judgment record fields

Every judgment/order should carry, at minimum:
- `doc_id`
- canonical title
- short title
- case numbers across stages
- neutral citation
- reporter citations
- court
- court level
- bench composition
- bench size
- Constitution Bench flag where relevant
- Full Bench flag where relevant
- dates decided/reserved/filed where available
- reportable flag where available
- party and advocate names where public
- jurisdiction tags
- binding/persuasive scope
- practice areas
- statutes applied
- statutes interpreted
- old/new criminal-code section references
- ratio
- obiter
- outcome
- proceeding-family link
- final-authority flag
- validity status
- override links such as overruled/modified/distinguished/followed
- language / translation status
- full text with paragraph markers
- OCR confidence where relevant
- source URL
- checksum
- parser version
- ingestion run id

## 26.2 Proceeding-family fields

Every proceeding family should carry:
- `proceeding_family_id`
- originating matter
- CNR where available
- ordered family members
- lead case
- connected matters
- transfer history
- renumbering history
- current stage
- final authority
- operative stay order where relevant

## 26.3 Section fields

Every section should carry:
- stable section id
- act id
- section number
- heading
- current text
- original text where reconstructable
- amendment history
- effective date range
- in-force status
- old/new criminal-code crosswalk where relevant
- schedule/form links
- interpreting-case links
- subordinate-legislation links created under that section’s power

## 27. Complete Knowledge Graph Architecture

The graph needs more than judgments and statutes.

Node families should include at least:
- judgments/orders
- statutes
- sections
- regulations/notifications/circulars
- Constitution articles
- constitutional amendments
- tribunal orders
- doctrine nodes
- practice-area nodes
- judges
- parliamentary/debate nodes
- Law Commission report nodes

Relationship families should include at least:
- citation and treatment relationships
- appeal and review relationships
- SLP and remand relationships
- stay/supersession relationships
- statute interpretation/application relationships
- amendment/repeal/commencement relationships
- doctrine membership/evolution relationships
- conflict relationships
- authorship/bench relationships
- legislative-history relationships

Doctrine clusters must be precomputed for major topics such as:
- Basic Structure
- privacy
- Article 21 expansion
- equality / classification
- anticipatory bail
- default bail
- promissory estoppel
- res judicata
- natural justice
- proportionality
- tax anti-avoidance
- absolute liability
- public trust doctrine

## 28. Freshness And Validity Engine At Maximum Precision

The validity engine must operate at different cadences and propagate change.

Freshness cycles should distinguish:
- daily sources
- weekly sources
- monthly sources
- event-triggered legal-change sources

Event-triggered sources must include:
- constitutional amendments
- commencement notifications
- repeal notifications
- overruling Supreme Court judgments
- court-rule changes
- budget/finance-act changes
- major regulator circular updates

Validity cascade rule examples:
- statute amendment -> section text update -> chunk re-embedding -> affected judgment warning analysis
- overruling judgment -> prior judgment invalidation -> follower warning states -> doctrine-cluster refresh
- High Court reversed by Supreme Court -> final-authority shift -> citing judgments warned if they relied on the reversed authority

## 29. Retrieval Design Must Follow Corpus Design

The corpus is only correct if it supports the query classes NyayaRAG already routes.

Examples:
- statutory query -> current section text + amendment history + key interpreting authorities + subordinate instruments
- doctrinal query -> founding case + evolution chain + current position + pending uncertainty if any
- document-specific criminal query -> current-code sections + old-code equivalents + bail/procedure jurisprudence
- multi-hop constitutional query -> articles + amendments + doctrinal chain + latest authoritative judgment

## 30. What Is Not Law

Never place the following in Layer A canonical truth:
- news articles
- blogs
- unofficial legal summaries
- social-media threads
- coaching materials
- moot memorials
- community notes
- unsourced explainers
- AI-generated summaries without official provenance

These may later exist only in a clearly non-canonical discovery layer, if at all.

## 31. Gold Truth Set Minimum Specification

Before any production ingestion run is trusted, NyayaRAG should manually verify at least:
- complete trial-to-Supreme Court appellate chains
- batch matter clusters with lead-case logic
- constitutional amendment chains
- criminal-code crosswalk fixtures
- amendment/re-amendment fixtures
- overruling chains with downstream followers
- intra-High-Court single-bench to division-bench chains
- Full Bench reference patterns
- Constitution Bench reference-and-answer pairs

The detailed fixture shapes remain in:
- [GOLD_FIXTURE_MATRIX.md](/Users/mohanganesh/project002/data/collection/GOLD_FIXTURE_MATRIX.md)

## 32. Final Standard

The real standard is:

`what a senior advocate's clerk would verify before allowing a case or section to be cited in court`

That means NyayaRAG must always structurally verify:
- the citation exists
- the source is correctly identified
- the proposition is supported
- the judgment is still good law
- the judgment is the right point in the appeal chain
- the statute text is the correct current text for the relevant date

That standard must not be lowered.
