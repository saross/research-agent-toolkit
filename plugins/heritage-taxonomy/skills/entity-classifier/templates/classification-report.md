# {ENTITY_TYPE} classification results

**Date:** {DATE}
**Entity type:** {ENTITY_TYPE_FORMAL}
**Method:** contextual reading by the entity-classifier skill (heritage-taxonomy plugin, version
{PLUGIN_VERSION})
**Mentions analysed:** {TOTAL_COUNT}
**Entities:** {ENTITY_COUNT}

---

## Classification summary

The counts in this section are tallied by the plugin's
`tally_classifications.py` from the per-mention records below, not by
hand.

### Mentions

| Mention label | Count | Percentage | Flagged |
| --- | --- | --- | --- |
| Building | {BUILDING_COUNT} | {BUILDING_PCT}% | {BUILDING_FLAGGED} |
| Organisation | {ORGANISATION_COUNT} | {ORGANISATION_PCT}% | {ORGANISATION_FLAGGED} |
| Both | {BOTH_COUNT} | {BOTH_PCT}% | {BOTH_FLAGGED} |
| **Total** | **{TOTAL_COUNT}** | **100%** | **{FLAGGED_COUNT}** |

Percentages are of mentions analysed, flagged ones included, rounded to
one decimal place. "Flagged" counts the mentions whose flag is still
open (for review). A mention is labelled both only when that one mention
carries spatial and agency indicators together.

### Entity roll-up

| Entity | Mentions | Building | Org. | Both | Flagged | Provisional | Supported | Recommendation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| {ENTITY} | {E_TOTAL} | {E_BLDG} | {E_ORG} | {E_BOTH} | {E_FLAG} | {E_PROV} | {E_SUPP} | {E_REC} |

**Entities by recommendation:** {ENTITY_BUILDING_COUNT} building only,
{ENTITY_ORGANISATION_COUNT} business or organisation only,
{ENTITY_BOTH_COUNT} both, and {ENTITY_PENDING_COUNT} pending review.

Each entity's labels are combined twice. The **provisional** union takes
all its mentions; the **supported** union leaves out mentions still for
review, and is "unresolved" if none is left. A union is both if it
includes both building and organisation, or any one mention that is
both; otherwise it is the one label its mentions share. Where the two
unions agree, that is the recommended facet; where they differ, the
recommendation is **pending review** until the flagged mentions are
settled. Flagged mentions stay in every count above; none is discarded.

---

## Detailed analysis

{MENTION_ANALYSES}

Each mention uses the per-mention template in the skill, followed by a
review block for the human reviewer:

```text
### Mention N: short title
[Entity, item, classification, confidence, flag, reasoning, indicators, context]

**HUMAN REVIEW:**
- [ ] Confirm classification
- [ ] Change to: [ ] building  [ ] organisation  [ ] both

**Notes:**

**Additional or alternative tags:**
```

To settle a flagged mention, change its `for review:` to `resolved:` and
the decision, correct the classification if need be, and run the tally
again.

---

## Pattern analysis

### Building indicators found

{BUILDING_PATTERNS}

### Business or organisation indicators found

{BUSINESS_PATTERNS}

### Dual-nature indicators (both)

{BOTH_PATTERNS}

---

## Taxonomy implications

### Current structure

```text
{CURRENT_TAXONOMY}
```

### Recommended structure

```text
{RECOMMENDED_TAXONOMY}
```

### Changes required

{TAXONOMY_CHANGES}

For each recommended leaf node, say whether the building and organisation
aspects are distinguished intrinsically (different names, such as a hall
and a lodge) or need a parenthetical qualifier (such as "Imperial Hotel
(building)" and "Imperial Hotel (business)").

---

## Specific establishments identified

{SPECIFIC_ESTABLISHMENTS}

---

## Comparison with other entity types (optional)

Include only entity types this project has already classified, with their
own figures. The percentages are of mentions.

| Entity type | Building % | Business or organisation % | Both % | Dominant pattern |
| --- | --- | --- | --- | --- |
| {ENTITY_TYPE} | {BUILDING_PCT}% | {ORGANISATION_PCT}% | {BOTH_PCT}% | {DOMINANT_PATTERN} |

---

## Method notes

- **Spatial indicators** point to the building: locative prepositions (at,
  in, near), events held at the place, physical descriptions, and
  construction or damage.
- **Agency indicators** point to the business or organisation: ownership
  and management, financial operations, services, membership and
  subscriptions, and committees and governance.
- **Unit:** the mention. Each reference to the entity is labelled on its
  own indicators, so a passage that names the entity twice, by two
  explicit name or short-form mentions, gives two records. A pronoun or
  elliptical reference joins the mention it refers back to; one with an
  ambiguous antecedent is flagged, not attached.
- **Both:** for a mention, a single mention carrying spatial and agency
  indicators together; for an entity's union, mentions that include both
  building and organisation, or any one mention that is both.
- **Flagged mentions** count in the mention totals and the provisional
  union, but not in the supported union. An entity whose two unions
  differ is pending review; no flagged record is discarded.
- **Counts:** tallied by the plugin's `tally_classifications.py` from the
  per-mention records.

**Overall confidence:** {CONFIDENCE_LEVEL}

---

## Next steps

1. **Review the classifications**, starting with the flagged mentions
   and the entities pending review, using the review block under each
   mention; then run the tally again.
2. **Apply the approved classifications** to the project's taxonomy and
   tags, by the project's own procedure.
3. **Record the decision** where the project keeps its decisions.
