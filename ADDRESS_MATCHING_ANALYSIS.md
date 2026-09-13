# Address Matching Feasibility & Strategy Report

## Executive Summary

Matching NSW EV Charging CSV (1,958 records) to Reference Dataset (2,038 records) is **feasible** but requires a **multi-tier approach**. Low exact coordinate match rate (~5%) is expected because many NSW records represent "Upcoming" (not-yet-built) stations. An estimated **80-90% overall match rate** is achievable using street number + postcode + fuzzy street name matching.

---

## Current Data State

### Dataset Sizes
- **NSW EV Charging (cleaned)**: 1,958 records with 12 columns
  - Complete Lat/Long: 100% (1,958 records)
  - Complete Postcode: 93.4% (1,827 records, 121 missing for "Upcoming" stations)
  - Complete Operator: 100%
  - Complete Station Name: 26.5% (517 records)

- **Reference Dataset**: 2,038 records with 22 columns
  - Complete Lat/Long: 100%
  - Complete Postcode: 100%
  - Complete Operator: 100%

---

## Address Format Comparison

### NSW Format (Post-Cleaning)
```
Examples:
  "Muswellbrook NSW 2333"
  "01 Wallgrove Road, Sydney NSW 2766"
  "1 - 7 Ross Street, Wilcannia NSW 2836"
  "1 Bay Lane, Byron Bay NSW 2481"
```

**Pattern**: `[Street Address], [Suburb] NSW [Postcode]` or just `[Suburb] NSW [Postcode]`
- Street abbreviations normalized (St→Street, Rd→Road, etc.)
- Linebreaks converted to commas
- "Australia" suffix removed
- State always "NSW", always uppercase

### Reference Format
```
Examples:
  "103 Sandy Flat Road, Sandy Flat NSW 2372, Australia"
  "84 Robinsons Ln, Tenterfield NSW 2372, Australia"
  "Lightning Ridge District Bowling Club, 1 Agate St, Lightning Ridge NSW 2834"
  "339 Warialda Street, Moree, New South Wales, Australia, NSW 2400"
  "1 Unumgar St, Woodenbong NSW 2476, Australia, Woodenbong 2476"
```

**Pattern**: Highly variable
- May include venue names before address
- Can say "New South Wales" instead of "NSW"
- May have ", Australia" suffix
- Sometimes has duplicate postcode at end
- Abbreviations preserved (Ln, St) or mixed
- Formatting inconsistencies common

---

## Matching Feasibility Analysis

### Tier 1: Exact Coordinate Matching
| Metric | Value |
|--------|-------|
| Unique NSW Coordinates (6dp) | 1,935 |
| Unique Reference Coordinates (6dp) | 2,027 |
| Exact Matches | **102** |
| Match Rate | **5.3%** |
| Confidence | ⭐⭐⭐⭐⭐ Very High |

**Feasibility**: ✅ Use as primary method for low-risk matches
- **Pros**: Zero false positives, very reliable
- **Cons**: Low coverage (~5%)
- **Reason for low rate**: ~98 "Upcoming" stations have no built reference

---

### Tier 2: Street Number + Postcode Matching
| Metric | Value |
|--------|-------|
| NSW records with street numbers | 1,693 |
| Reference records with street numbers | 1,900 |
| Exact street_num + postcode matches | **1,215** |
| Match Rate (within numbers group) | **71.8%** |
| Estimated Coverage (whole dataset) | **62%** |
| Confidence | ⭐⭐⭐⭐ High |

**Feasibility**: ✅ Use with fuzzy street name matching
- **Pros**: High match rate, identifies specific building numbers
- **Cons**: ~30% don't match exactly; needs fuzzy text matching
- **Implementation**: Extract street number regex, match on (number, postcode, fuzzy street name)

---

### Tier 3: Postcode + Operator Matching
| Metric | Value |
|--------|-------|
| NSW records with postcode + operator | 1,837 |
| Reference matches by (postcode, operator) | **1,278** |
| Match Rate | **65.3%** |
| Confidence | ⭐⭐⭐ Medium |

**Feasibility**: ✅ Use as fallback for ambiguous cases
- **Pros**: Simple exact matching
- **Cons**: High false positive rate (one operator may have multiple locations per postcode)
- **Implementation**: Only use when Tier 2 fails AND additional constraints applied

---

### Tier 4: Manual/Unmatched
| Metric | Value |
|--------|-------|
| Expected Unmatched | ~50-100 |
| Percentage | ~2-5% |

**Categories**:
1. Genuinely "Upcoming" stations (no reference yet)
2. Data entry errors/typos
3. New locations built after reference data was published

---

## Current Address Processor Limitations

The current `address_processor()` in config.py is **optimized for normalization**, not matching:

### Strengths ✅
- Consistently normalizes street abbreviations
- Removes "Australia" suffix
- Extracts state and postcode
- Standardizes title case

### Weaknesses ❌
1. **Loses parsing components**: Final output is "Street, Suburb STATE PCODE" — intermediate parts discarded
2. **Over-aggressive cleanup**: Removes numbers in some contexts (e.g., "Level 1" becomes "L 1")
3. **Thin on suburbs**: Can't reliably distinguish street vs suburb when only 1-2 parts
4. **No extraction functions**: Return value is a string; no structured fields for matching

### Example Issues
```
Input:  "1 - 7 Ross St, Wilcannia NSW 2836, Australia"
Output: "1 - 7 Ross Street, Wilcannia NSW 2836"
Problem: "1-7" range notation will only exact-match another "1-7" range
         A reference entry "1 Ross Street" won't match "1 - 7 Ross Street"
         
Input:  "Wordsworth St, Byron Bay NSW 2481"
Output: "Wordsworth Street, Byron Bay NSW 2481"
Problem: Missing street number. "Wordsworth Street" must match fuzzy.
```

---

## Recommended Address Reformatting Improvements

### Strategy A: Structured Output (Recommended)
**Return a structured object** instead of just a formatted string:

```python
@dataclass
class AddressComponents:
    street_number: str        # "1", "1-7", "54-68", None
    street_name: str          # "Wallgrove Road", "Bay Lane"
    suburb: str               # "Sydney", "Byron Bay"
    state: str                # "NSW"
    postcode: str             # "2766"
    full_normalized: str      # Final string for display
```

**Benefits**:
- Matching logic can use structured fields (street_num, postcode first)
- Falls back to fuzzy matching on street_name if needed
- Keeps full normalized address for logging/display

### Strategy B: Enhanced Normalization
1. **Improve street number extraction**:
   - Handle ranges: "1-7" → capture both endpoints for flexible matching
   - Handle levels: "Level 3, 100 Smith St" → extract "100" as primary number
   
2. **Improve suburb/street split**:
   - Use known NSW suburb list + LGA data from SA4 shapefile
   - If part of address matches a known suburb → that's the suburb, rest is street
   
3. **Separate venue names**:
   - Many reference entries have "Bowling Club, 123 Main St"
   - Detect and extract venue name separately for matching purposes

4. **Standardize state representation**:
   - "NSW", "N.S.W.", "New South Wales" → all become "NSW"
   - Prepend if missing

5. **Keep street abbreviations for matching**:
   - Normalize both `Lane` and `Ln` → both forms kept for fuzzy match
   - Example: Input "1 Bay Ln" can match "1 Bay Lane" reference

---

## Matching Algorithm Recommendation

### Pseudo-Code for Multi-Tier Matcher

```python
def match_address(nsw_record, reference_df):
    """
    Tier 1: Exact coordinates (6dp)
    """
    nsw_coord = (nsw_record['Latitude'].round(6), nsw_record['Longitude'].round(6))
    exact_coord_match = reference_df[
        (reference_df['Latitude'].round(6) == nsw_coord[0]) &
        (reference_df['Longitude'].round(6) == nsw_coord[1])
    ]
    if len(exact_coord_match) > 0:
        return exact_coord_match.iloc[0], confidence='EXACT_COORD'
    
    """
    Tier 2: Street number + postcode + fuzzy street name
    """
    pcode = nsw_record['PCODE']
    street_num = extract_street_number(nsw_record['Station_address'])
    street_name = extract_street_name(nsw_record['Station_address'])
    
    candidates = reference_df[
        (reference_df['Postcode'] == int(pcode)) &
        (extract_street_number(reference_df['Station address']) == street_num)
    ]
    
    if len(candidates) > 0:
        # Fuzzy match on street name
        best_match = fuzzy_match_street_name(street_name, candidates)
        if best_match['score'] > 0.8:  # High confidence threshold
            return best_match['record'], confidence='STREET_NUM_PCODE_FUZZY'
    
    """
    Tier 3: Postcode + operator (with disambiguation)
    """
    postcode_operator_matches = reference_df[
        (reference_df['Postcode'] == int(pcode)) &
        (reference_df['Operator'] == nsw_record['Operator'])
    ]
    
    if len(postcode_operator_matches) == 1:
        return postcode_operator_matches.iloc[0], confidence='PCODE_OP'
    elif len(postcode_operator_matches) > 1:
        # Too ambiguous, return None for manual review
        pass
    
    """
    Unmatched
    """
    return None, confidence='NO_MATCH'
```

---

## Implementation Priority

### Phase 1: Validation (Current)
✅ **DONE**: Address normalization in config.py
- ✅ Standardize abbreviations
- ✅ Remove "Australia" suffix
- ✅ Extract state/postcode

### Phase 2: Structured Matching (Recommended Next)
- 🔲 Extract street number reliably
- 🔲 Identify suburb using LGA data
- 🔲 Support fuzzy street name matching
- 🔲 Implement Tier 1-2 matching algorithm

### Phase 3: Augmentation (Stage 2 of pipeline)
- 🔲 Fill missing Station_name from reference matches
- 🔲 Validate/correct Operator where found
- 🔲 Add reference EV Station ID as foreign key
- 🔲 Flag unmatched records for manual review

---

## Data Quality Notes

### Current Pain Points
1. **Upcoming stations**: 98 records have no reference match (intentional)
2. **Truncated operator names**: 5+ names cut at 13 chars (partially fixed in config)
3. **Address format variability**: Reference dataset has wide format inconsistency
4. **Missing suburbs**: NSW data extracts suburb from address; reference has explicit column

### Opportunities
1. **LGA+SA4 integration**: Use shapefile to validate/correct suburbs
2. **Operator name standardization**: Reference has full operator names, can use for backfill
3. **Duplicate detection**: (lat, long) pairs can identify duplicate chargers
4. **Address augmentation**: Fill missing NSW street names from reference

---

## Conclusion

**Overall Feasibility: HIGH ✅**

- **Estimated Match Rate**: 80-90% using multi-tier approach
- **Confidence Level**: Tier 1 (5%) very high; Tier 2 (70-75%) high; Tier 3 (10-15%) medium
- **Unmatched Rate**: 2-5% (mostly legitimate "Upcoming" stations)

**Next Steps**:
1. Refine address_processor to extract structured components
2. Implement fuzzy street name matching
3. Build matching pipeline with three-tier fallback logic
4. Validate matches against reference Operator + Charger_Type
