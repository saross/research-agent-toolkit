# {ENTITY_TYPE} classification results

**Date:** {DATE}
**Entity type:** {ENTITY_TYPE_FORMAL}
**Method:** contextual reading by the entity-classifier skill (heritage-taxonomy plugin, version
{PLUGIN_VERSION})
**Mentions analysed:** {TOTAL_COUNT}

---

## Classification summary

| Classification | Count | Percentage |
| --- | --- | --- |
| Building only | {BUILDING_COUNT} | {BUILDING_PCT}% |
| Business or organisation only | {BUSINESS_COUNT} | {BUSINESS_PCT}% |
| Both | {BOTH_COUNT} | {BOTH_PCT}% |
| **Total** | **{TOTAL_COUNT}** | **100%** |

Percentages are of mentions analysed, rounded to one decimal place.

---

## Detailed analysis

{MENTION_ANALYSES}

Each mention uses the per-mention template in the skill, followed by a
review block for the human reviewer:

```text
### Mention N: descriptive title
[Entity, item, classification, confidence, reasoning, indicators, context]

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
own figures.

| Entity type | Building % | Business or organisation % | Both % | Dominant pattern |
| --- | --- | --- | --- | --- |
| {ENTITY_TYPE} | {BUILDING_PCT}% | {BUSINESS_PCT}% | {BOTH_PCT}% | {DOMINANT_PATTERN} |

---

## Method notes

- **Spatial indicators** point to the building: locative prepositions (at,
  in, near), events held at the place, physical descriptions, and
  construction or damage.
- **Agency indicators** point to the business or organisation: ownership
  and management, financial operations, services, membership and
  subscriptions, and committees and governance.
- **Both:** a single mention carrying spatial and agency indicators
  together.

**Overall confidence:** {CONFIDENCE_LEVEL}

---

## Next steps

1. **Review the classifications**, using the review block under each
   mention.
2. **Apply the approved classifications** to the project's taxonomy and
   tags, by the project's own procedure.
3. **Record the decision** where the project keeps its decisions.
