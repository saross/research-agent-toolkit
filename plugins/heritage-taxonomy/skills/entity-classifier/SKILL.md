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
- The entity's name shifts within the text between the structure and the organisation (a
  metonymic shift)
- Example: "Concert at the hotel [building], with the hotel [business] providing refreshments"

### Default Guidance

When indicators are **weak or absent**:

- **Hotels/inns**: Default to building (most newspaper mentions are locational)
- **Churches**: Consider denomination and context (worship events = building, governance =
  organisation)
- **Schools of Arts**: Consider activity (event venue = building, committee decisions =
  organisation)
- **Halls**: Usually buildings unless committee/management explicitly mentioned
- **Any other type, or where the guidance above gives no default and the context is weak**:
  take the stronger cue if there is one; otherwise give the likelier reading at low confidence
  and flag the mention for human review

## Output format

**For a batch, or whenever the user asks, write the results to a
Markdown file**, not only into the conversation: a file is an audit trail
that a reviewer can check and later sessions can build on. For a single
mention asked about in passing, answer in the conversation and offer to
write the file.

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
**Classification:** building | organisation | both
**Confidence:** high | medium | low

**Reasoning:**
[Two or three sentences explaining the classification, naming the indicators found in the context]

**Indicators found:**

- Building: [the indicators matched, or "none"]
- Organisation: [the indicators matched, or "none"]

**Context:**
> [The excerpt showing the mention and enough surrounding text to check it]
```

"Organisation" covers a business (a hotel as its proprietor or
management) as well as a body (a congregation, a committee, an order).

## Confidence Levels

- **High**: Multiple strong indicators present; classification unambiguous
- **Medium**: Some indicators present but context could support alternative reading
- **Low**: Minimal indicators; relying on defaults or general patterns

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

## Example analyses

### Entity: Carrington Hotel

**Item:** (example)
**Classification:** building
**Confidence:** high

**Reasoning:**
A strong locational phrase ("at the Carrington Hotel") with an event held there, and no sign of
the hotel acting as an agent. The hotel is purely the venue.

**Indicators found:**

- Building: locational phrases; events occurring
- Organisation: none

**Context:**
> "A concert was held at the Carrington Hotel last evening, attended by many prominent citizens."

---

### Entity: Imperial Hotel

**Item:** (example)
**Classification:** organisation
**Confidence:** high

**Reasoning:**
The hotel acts as an agent: it announces, closes, and completes work, in the active voice. There
are no spatial or locational cues.

**Indicators found:**

- Building: none
- Organisation: agency verbs; business operations

**Context:**
> "The Imperial Hotel has announced extensive renovations and will close for the season to
> complete the work."

---

### Entity: Megalong Hotel

**Item:** (example)
**Classification:** both
**Confidence:** high

**Reasoning:**
The first sentence treats the hotel as a business (its proprietor applies for a licence); the
second treats it as a venue (a dance held at it). Both aspects appear in the same passage.

**Indicators found:**

- Building: locational phrases; events occurring
- Organisation: ownership/management; legal agency

**Context:**
> "The Megalong Hotel proprietor applied for a licence renewal. Meanwhile, a dance was held at
> the hotel on Saturday evening."

---

### Entity: Katoomba Hotel (metonymy)

**Item:** (example)
**Classification:** organisation
**Confidence:** high

**Reasoning:**
"The hotel" stands for its management or proprietor, who can deny and contest; the building is
not meant.

**Indicators found:**

- Building: none
- Organisation: metonymy (agency verbs with the entity as subject); legal agency

**Context:**
> "The Katoomba Hotel denies responsibility for the incident and contests the charges."

## Working with Batch Data

When processing multiple entities:

1. **Process each mention independently** — don't let previous classifications bias current one
2. **Note patterns** — if same entity consistently appears as one type, mention this
3. **Flag outliers** — if entity classification differs from pattern, explain why
4. **Preserve context** — always include enough context for human to verify

## Other entity types

The heuristic carries over to any dual-nature type: inns and public houses, chapels, mechanics'
institutes, fraternal halls (the lodge building or the order), and schools (the facility or the
institution). Adjust the default guidance and the type-specific patterns for each.
