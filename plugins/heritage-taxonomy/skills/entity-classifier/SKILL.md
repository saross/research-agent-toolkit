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
arts, halls, lodges, and the like) in historical text, to decide where
each entity belongs in a faceted taxonomy:

- **Building or facility only** (a built-environment facet)
- **Business or organisation only** (an agents facet)
- **Both** (polyhierarchical: it appears in both facets)

The unit of classification is the **mention**. Each mention is labelled
on its own evidence, and the entity's place in the taxonomy is then
rolled up from all its mentions (see "Both, and the entity roll-up"
below).

It reads each mention in context and applies a linguistic heuristic,
which gives a more careful classification than fixed text patterns.

The heuristic was developed on 19th-century Australian newspaper text,
for rationalising the folksonomy of a digitised local-history collection
into a controlled vocabulary aligned with the principles of the Getty Art
& Architecture Thesaurus (AAT). Its indicators are English-language; its
defaults (below) reflect that corpus, and may need adjusting for others.

## Role

Act as an expert in classifying entities mentioned in historical text,
for a controlled-vocabulary taxonomy aligned with AAT principles.

## Task

Label each mention of a dual-nature entity:

- **(a) Building:** the mention refers to the entity as a physical
  structure (built-environment facet)
- **(b) Organisation:** the mention refers to the entity as an agent or
  operator (agents facet)
- **(c) Both:** the one mention carries spatial and agency indicators
  together

Then roll the labels up by entity.

A **mention** is one reference to the entity, by its name or by a short
form ("the hotel", "the hotel's parlour"). Indicators belong to the
mention they describe: a pronoun that refers back to it ("its tariff")
or an elliptical reference to its spaces ("the room") adds to that
mention rather than starting a new one. A passage, or a numbered item in
a batch, that refers to the entity twice holds two mentions, and each
gets its own record.

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
  - When a passage about the entity says "at/in the [room/hall/library]" without saying whose,
    read it as the entity's own building
  - Example: "Committee of the School of Arts was to be held at the room" → "the room" = School of
    Arts' room = building indicator (and since "Committee of" is a governance indicator on the
    same mention, this mention is both)

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
- **Membership and subscriptions**: "members of [entity]", "joined [entity]", "[entity]
  subscribers", "subscriptions to [entity]"
- **Committees and governance**: "[entity] committee", "trustees of [entity]", "annual meeting of
  [entity]", "[entity] elected its officers"

### Metonymy

When the entity name is used as **shorthand for people/organisation**, classify by intended
referent:

- "The hotel denies the accusation" → Organisation (hotel = proprietor/management, a business)
- "The church condemns the proposal" → Organisation (church = congregation/leadership)
- "Meeting **at** the church" → Building (church = physical venue)

### Passive vs Active Voice

- **Passive**: "[entity] was refurbished" → Building (recipient of action)
- **Active**: "[entity] refurbished its premises" → Organisation (agent of action)

### Both, and the entity roll-up

Label a mention **both** only when that one mention carries spatial and agency indicators
together:

- Example: "A ball was held at the Carrington Hotel, whose proprietor provided the supper". One
  mention, placed by "held at" and acting through "whose proprietor"

When the entity's name shifts within a passage between the structure and the organisation (a
metonymic shift), each mention takes its own label:

- Example: "Concert at the hotel [building], with the hotel [organisation] providing
  refreshments". Two mentions, one building and one organisation

**Entity roll-up.** Once every mention is labelled, group the mentions by entity. An entity is
**both** in the taxonomy if its mentions include both building and organisation, or if any one of
its mentions is both; otherwise it takes the one label its mentions share. The Megalong example
below shows two mentions rolling up to both.

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
  and flag the mention for human review, in its **Flag** field (see the church example)

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
- **Include:** a record for each mention, the mention counts and the
  per-entity roll-up, a summary of patterns, taxonomy recommendations,
  and comparison tables only where the project has already classified
  other entity types, with their own figures.
- **Counts:** once the per-mention records are written, tally them with a
  short script that reads each record's `**Entity:**` and
  `**Classification:**` lines from the file, not by hand. It counts the
  mentions under each label, then applies the roll-up rule to each
  entity; fill the summary and the roll-up table from its output. A hand
  count drifts over a long batch, and a script can be run again when a
  reviewer changes a label.
- **Plugin version** for the report's method line: the `version` in
  `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`.

### Per-mention template

For each mention analysed, give:

```text
### Mention N: [short title]
**Entity:** [entity name, written the same way in every mention of it]
**Item:** [article or document title]
**Classification:** building | organisation | both
**Confidence:** high | medium | low
**Flag:** none | for review: [the question the reviewer needs to settle]

**Reasoning:**
[As long as a reviewer needs to check it, usually two or three sentences, naming the
indicators found in the context]

**Indicators found:**

- Building: [the indicators matched, or "none"]
- Organisation: [the indicators matched, or "none"]

**Context:**
> [The excerpt showing the mention and enough surrounding text to check it; where the
> excerpt holds more than one mention of the entity, bold this one]
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

These are illustrative: they show the format and how the indicators decide a reading, not how
often each classification or confidence level occurs.

### Mention 1: a concert at the Carrington Hotel

**Entity:** Carrington Hotel
**Item:** (example)
**Classification:** building
**Confidence:** high
**Flag:** none

**Reasoning:**
A strong locational phrase ("at the Carrington Hotel") with an event held there, and no sign of
the hotel acting as an agent. The hotel is purely the venue.

**Indicators found:**

- Building: locational phrases; events occurring
- Organisation: none

**Context:**
> "A concert was held at the Carrington Hotel last evening, attended by many prominent citizens."

---

### Mention 2: the Imperial Hotel's renovations

**Entity:** Imperial Hotel
**Item:** (example)
**Classification:** organisation
**Confidence:** high
**Flag:** none

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

### Mention 3: the Megalong Hotel's licence renewal

**Entity:** Megalong Hotel
**Item:** (example)
**Classification:** organisation
**Confidence:** high
**Flag:** none

**Reasoning:**
This mention names the hotel only through its proprietor, who applies for a licence renewal:
ownership and a legal act, with nothing placing anyone at the hotel. The dance in the next
sentence belongs to the passage's second mention, not to this one.

**Indicators found:**

- Building: none
- Organisation: ownership/management; legal agency

**Context:**
> "The **Megalong Hotel** proprietor applied for a licence renewal. Meanwhile, a dance was held
> at the hotel on Saturday evening."

---

### Mention 4: a dance at the Megalong Hotel

**Entity:** Megalong Hotel
**Item:** (example)
**Classification:** building
**Confidence:** high
**Flag:** none

**Reasoning:**
"The hotel" is the venue: a dance "was held at" it. The proprietor and the licence belong to the
first mention, so they do not make this one both.

**Indicators found:**

- Building: locational phrases; events occurring
- Organisation: none

**Context:**
> "The Megalong Hotel proprietor applied for a licence renewal. Meanwhile, a dance was held at
> **the hotel** on Saturday evening."

**Roll-up:** the Megalong Hotel has one organisation mention and one building mention, so it is
**both** in the taxonomy.

---

### Mention 5: the Katoomba Hotel denies the charges (metonymy)

**Entity:** Katoomba Hotel
**Item:** (example)
**Classification:** organisation
**Confidence:** high
**Flag:** none

**Reasoning:**
"The hotel" stands for its management or proprietor, who can deny and contest; the building is
not meant.

**Indicators found:**

- Building: none
- Organisation: metonymy (agency verbs with the entity as subject); legal agency

**Context:**
> "The Katoomba Hotel denies responsibility for the incident and contests the charges."

---

### Mention 6: Mr Smith, "of the Wesleyan Church" (weak context)

**Entity:** Wesleyan Church, Lawson
**Item:** (example)
**Classification:** organisation
**Confidence:** low
**Flag:** for review: is the church named as Mr Smith's congregation (organisation), or as the
place he lives or comes from (building)?

**Reasoning:**
The church appears only in "of the Wesleyan Church", with no event, locational phrase, or agency
verb attached; the gathering he attended is not placed at the church. Read as an affiliation, the
phrase points to the congregation, but it does not say whether Mr Smith is a member, an officer,
or simply someone from there, so it falls short of the membership indicator. The same "Mr X,
of …" form often gives a place of residence ("Mr J. Smith, of Lawson"), which leaves a building
reading open. The default guidance gives churches no default, so the likelier reading,
organisation, is given at low confidence and flagged.

**Indicators found:**

- Building: none
- Organisation: none matched ("of the Wesleyan Church" suggests membership but does not state
  it)

**Context:**
> "Among those present was Mr. J. Smith, of the Wesleyan Church, Lawson."

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
