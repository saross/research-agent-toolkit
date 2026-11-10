---
name: entity-classifier
description: >-
  Classify mentions of dual-nature entities in historical text (hotels,
  churches, schools of arts, halls, lodges) as building only, business or
  organisation only, or both, by contextual linguistic analysis, for a
  faceted taxonomy. Use when classifying such mentions, reviewing
  automated classifications, or batch-processing entity mentions.
---

# Entity classifier

## Purpose

Classifies mentions of dual-nature entities (hotels, churches, schools of
arts, halls, lodges, and the like) in historical text, to decide whether
each should be tagged as:

- **Building or facility only** (a built-environment facet)
- **Business or organisation only** (an agents facet)
- **Both** (polyhierarchical: it appears in both facets)

It reads each mention in context and applies a linguistic heuristic,
which gives a more careful classification than fixed text patterns.

The heuristic was developed on 19th-century Australian newspaper text,
for rationalising the folksonomy of a digitised local-history collection
into a controlled vocabulary aligned with the principles of the Getty Art
& Architecture Thesaurus (AAT). Its indicators are English-language; its
defaults (below) reflect that corpus, and may need adjusting for others.

## When to use

- Classifying hotel mentions as buildings or businesses
- Deciding a church's classification (building or religious organisation)
- Analysing schools of arts (venue or cultural society)
- Any entity that can be both a physical structure and an organisational
  agent
- Reviewing and checking automated classifications
- Batch-processing entity mentions, for example from a reference library
  of newspaper articles

## Role

Act as an expert in classifying entities mentioned in historical text,
for a controlled-vocabulary taxonomy aligned with AAT principles.

## Task

Analyse each mention of a dual-nature entity and decide its facet:

- **(a) Building or facility only:** the entity is referred to solely as
  a physical structure (built-environment facet)
- **(b) Business or organisation only:** the entity is referred to solely
  as an agent or operator (agents facet)
- **(c) Both (polyhierarchical):** the context shows both spatial and
  agency characteristics

## Classification Heuristic

### Building/Facility Indicators

Look for evidence that the entity is being used as a **location or physical space**:

**Strong indicators:**

- **Locational phrases**: "at [entity]", "in [entity]", "within [entity]", "near [entity]",
  "opposite [entity]"
- **Movement to/from**: "going to [entity]", "arriving at [entity]", "leaving [entity]", "travelled
  to [entity]"
- **Events occurring**: "meeting held at [entity]", "concert at [entity]", "ball at [entity]",
  "auction at [entity]"
- **Accommodation**: "staying at [entity]", "lodging at [entity]", "resided at [entity]"
- **Physical features**: "[entity]'s rooms", "[entity]'s bar", "[entity]'s verandah", "[entity]
  building"
- **Construction/damage**: "[entity] was built", "fire destroyed [entity]", "[entity] was
  demolished"
- **Venue usage**: "in [entity]'s yard", "at [entity]'s grounds"
- **Elliptical spatial references**: "at the room" (when discussing [entity]), "in the hall"
  (entity's space)
  - **CRITICAL**: When entity discussion includes "at/in the [room/hall/library]" without specifying
    whose, assume it refers to the entity's building
  - Example: "Committee of the School of Arts was to be held at the room" → "the room" = School of
    Arts' room = building indicator

### Business/Organisation Indicators

Look for evidence that the entity is acting as an **agent, operator, or organisation**:

**Strong indicators:**

- **Agency verbs**: "[entity] is expanding", "[entity] announced", "[entity] opened", "[entity]
  refurbished"
- **Ownership/management**: "[entity] proprietor", "owner of [entity]", "[entity] manager", "keeper
  of [entity]"
- **Business operations**: "[entity] licensed", "[entity] trading", "[entity] conducting business"
- **Services provided**: "[entity] offers", "[entity] provides", "[entity] caters"
- **Financial actions**: "[entity] purchased", "[entity] selling", "[entity] revenue"
- **Employment**: "[entity] employs", "[entity] hiring staff"
- **Legal agency**: "[entity] was fined", "[entity] applied for licence", "[entity] prosecuted"
- **Competition**: "[entity] competing with", "[entity] attracting customers"

### Metonymy (Important!)

When the entity name is used as **shorthand for people/organisation**, classify by intended
referent:

- "The hotel denies the accusation" → Business (hotel = proprietor/management)
- "The church condemns the proposal" → Organisation (church = congregation/leadership)
- "Meeting **at** the church" → Building (church = physical venue)

### Passive vs Active Voice

- **Passive**: "[entity] was refurbished" → Building (recipient of action)
- **Active**: "[entity] refurbished its premises" → Business (agent of action)

### Both (Polyhierarchical) Classification

Use "both" when:

- Context contains **both spatial AND agency indicators**
- Text treats entity as **both place and actor** in same passage
- Example: "Concert at the hotel [building], with the hotel [business] providing refreshments"

### Default Guidance

When indicators are **weak or absent**:

- **Hotels/inns**: Default to building (most newspaper mentions are locational)
- **Churches**: Consider denomination and context (worship events = building, governance =
  organisation)
- **Schools of Arts**: Consider activity (event venue = building, committee decisions =
  organisation)
- **Halls**: Usually buildings unless committee/management explicitly mentioned

## Output format

**Always write classification results to a Markdown file**, never only in
the conversation. Chat is ephemeral; a file is an audit trail that a
reviewer can check, that later sessions can build on, and that documents
the method.

- **Location:** where the project keeps such results. If it has no
  convention, use `outputs/<entity-type>/<entity-type>-classification-results.md`
  in the project.
- **Template:** this skill's report template,
  `${CLAUDE_PLUGIN_ROOT}/skills/entity-classifier/templates/classification-report.md`,
  unless the project has its own.
- **Include:** the analysis of each mention, a summary of patterns,
  taxonomy recommendations, and comparison tables.

### Per-mention template

For each mention analysed, give:

```text
### Entity: [entity name]
**Item:** [article or document title]
**Classification:** building | business | both
**Confidence:** high | medium | low

**Reasoning:**
[Two or three sentences explaining the classification, naming the indicators found in the context]

**Indicators found:**
- Building: [the indicators matched, or "none"]
- Business: [the indicators matched, or "none"]

**Context:**
> [The excerpt showing the mention and enough surrounding text to check it]
```

## Confidence Levels

- **High**: Multiple strong indicators present; classification unambiguous
- **Medium**: Some indicators present but context could support alternative reading
- **Low**: Minimal indicators; relying on defaults or general patterns

## Special Cases Requiring "Both"

1. **Mixed signals in same passage**: Both spatial and agency cues present
2. **Metonymic shift**: Entity name refers to both structure and organisation within text
3. **Parallel constructions**: Text explicitly treats entity as both place and actor

## Quality Standards

- **Evidence-based**: Every classification must be grounded in textual evidence
- **Audit trail**: Reasoning must be clear enough for human reviewer to verify
- **Conservative**: When truly ambiguous, prefer established defaults over speculation
- **Spelling**: follow the user's conventions (their `CLAUDE.md`).

## Taxonomy Naming Principles

**Intrinsic vs Parenthetical Disambiguation:**

A taxonomy built this way aims for **unique leaf nodes**. When possible, distinguish between
building and organisation aspects **intrinsically through naming**, falling back to parenthetical
qualifiers only when necessary.

**Use intrinsic naming distinction (no parenthetical):**

- "Halls" (buildings) vs "Lodges" (organisations) — different words naturally distinguish the
  concepts
- "Boarding houses" (buildings) vs "Hospitality businesses" (organisations) — hierarchy context
  makes it clear
- Buildings use architectural terms; organisations use corporate/group terms

**Use parenthetical qualifiers when necessary:**

- Churches: "Methodist Church (building)" vs "Methodist Church (organisation)" — same name requires
  disambiguation
- Hotels: "Imperial Hotel (building)" vs "Imperial Hotel (business)" — same name requires
  disambiguation
- Generic terms: "church (building)" vs "church (organisation)"

**Why this matters for classification:**

When you recommend taxonomy placement, consider:

1. Can the building/organisation aspects be distinguished by different entity names? (e.g., "Masonic
   Hall" for building, "Freemasons" for organisation)
2. Or do they share the same name and require parenthetical qualifiers? (e.g., "Imperial Hotel
   (building)" and "Imperial Hotel (business)")

This informs whether the entity should use:

- **Separate leaf nodes** with intrinsic distinction (halls vs lodges)
- **Disambiguated leaf nodes** with parenthetical qualifiers (hotel (building) vs hotel (business))

## Example Analyses

### Example 1: Building Only

**Context:** "A concert was held at the Carrington Hotel last evening, attended by many prominent
citizens."

**Classification:** building
**Reasoning:** Strong locational indicator ("at the Carrington Hotel") with event occurrence. No
agency or business operation signals. Hotel functions purely as venue.
**Indicators:** Building: locational_prep, events_at | Business: none

---

### Example 2: Business Only

**Context:** "The Imperial Hotel has announced extensive renovations and will close for the season
to complete the work."

**Classification:** business
**Reasoning:** Hotel acts as agent (announcing, closing, completing work). Active voice with agency
verbs. No spatial or locational cues.
**Indicators:** Building: none | Business: agency_verbs, business_ops

---

### Example 3: Both (Polyhierarchical)

**Context:** "The Megalong Hotel proprietor applied for a licence renewal. Meanwhile, a dance was
held at the hotel on Saturday evening."

**Classification:** both
**Reasoning:** First sentence treats hotel as business (proprietor agency, licensing). Second
sentence treats hotel as venue (event location). Both aspects present in same context.
**Indicators:** Building: locational_prep, events_at | Business: proprietor_subject, legal_agent

---

### Example 4: Metonymy — Business

**Context:** "The Katoomba Hotel denies responsibility for the incident and contests the charges."

**Classification:** business
**Reasoning:** Metonymic usage — "hotel" stands for hotel management/proprietor (agents who can deny
and contest). Not referring to physical building.
**Indicators:** Building: none | Business: metonymy (agency verbs with abstract subject)

---

## Working with Batch Data

When processing multiple entities:

1. **Process each mention independently** — don't let previous classifications bias current one
2. **Note patterns** — if same entity consistently appears as one type, mention this
3. **Flag outliers** — if entity classification differs from pattern, explain why
4. **Preserve context** — always include enough context for human to verify

## Place in a project's workflow

- **Input:** entity mentions with their full surrounding text (for
  example newspaper articles held in a reference library)
- **Process:** analyse each mention in context with this framework
- **Output:** structured recommendations for facet assignment
- **Review:** a human expert approves or changes each classification
- **Application:** the approved classifications update the project's tag
  map or taxonomy, by the project's own procedure

## Notes for Reuse

This skill is designed to be reusable across any dual-nature entity type:

- **Hotels, inns, public houses** (accommodation vs hospitality business)
- **Churches, chapels** (building vs religious organisation)
- **Schools of Arts, Mechanics' Institutes** (hall vs cultural society)
- **Fraternal halls** (lodge building vs fraternal order)
- **Schools** (educational facility vs educational institution)

Adjust the default guidance and entity-specific patterns as needed for each type.
