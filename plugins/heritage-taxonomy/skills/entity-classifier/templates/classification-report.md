# {ENTITY_TYPE} classification results

**Date:** {DATE}
**Entity type:** {ENTITY_TYPE_FORMAL}
**Method:** contextual reading by the entity-classifier skill (heritage-taxonomy plugin, version
{PLUGIN_VERSION})
**Mentions analysed:** {TOTAL_COUNT}
**Entities:** {ENTITY_COUNT}

---

## Classification summary

The counts in this section are tallied by a script from the per-mention
records below, not by hand.

### Mentions

| Mention label | Count | Percentage |
| --- | --- | --- |
| Building | {BUILDING_COUNT} | {BUILDING_PCT}% |
| Organisation | {ORGANISATION_COUNT} | {ORGANISATION_PCT}% |
| Both | {BOTH_COUNT} | {BOTH_PCT}% |
| **Total** | **{TOTAL_COUNT}** | **100%** |

Percentages are of mentions analysed, rounded to one decimal place. A
mention is labelled both only when that one mention carries spatial and
agency indicators together.

### Entity roll-up

| Entity | Mentions | Building | Organisation | Both | Flagged | Taxonomy facet |
| --- | --- | --- | --- | --- | --- | --- |
| {ENTITY_NAME} | {E_TOTAL} | {E_BUILDING} | {E_ORG} | {E_BOTH} | {E_FLAGGED} | {E_FACET} |

**Entities by facet:** {ENTITY_BUILDING_COUNT} building only,
{ENTITY_ORGANISATION_COUNT} business or organisation only, and
{ENTITY_BOTH_COUNT} both.

An entity is both if its mentions include both building and
organisation, or if any one of them is both; otherwise it takes the one
label its mentions share. "Flagged" counts the mentions marked for
review, so a reviewer can see which facets rest on a doubtful reading.

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
  own indicators, so a passage that names the entity twice gives two
  records.
- **Both:** for a mention, a single mention carrying spatial and agency
  indicators together; for an entity, mentions that include both
  building and organisation, or any one mention that is both.
- **Counts:** tallied by a script from the per-mention records.

**Overall confidence:** {CONFIDENCE_LEVEL}

---

## Next steps

1. **Review the classifications**, starting with the flagged mentions,
   using the review block under each mention.
2. **Apply the approved classifications** to the project's taxonomy and
   tags, by the project's own procedure.
3. **Record the decision** where the project keeps its decisions.
