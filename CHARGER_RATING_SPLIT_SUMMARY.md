# Charger Rating Feature Splitting - Implementation Summary

## Overview

Split the mixed `Charger_rating` column into two separate features: `AC_charger_rating` and `DC_charger_rating` for better feature representation and analysis.

## Problem Statement

### Original Issue
The `Charger_rating` column mixed AC and DC charger ratings:
- AC entries like "22 kW", "7 kW"
- DC entries like "150 kW", "175 kW", "250 kW"
- Some entries had placeholder "AC" value (should be NaN)
- No way to distinguish which rating applies to which charger type

### Why Split?
1. **Feature Independence**: AC and DC ratings have different ranges and distributions
2. **Machine Learning**: Separate features prevent cross-type confusion in models
3. **Analysis**: Easier to analyze AC vs DC characteristics separately
4. **Data Quality**: Eliminates ambiguity in interpretation

## Solution Implementation

### Feature Extraction Functions

**`extract_ac_charger_rating(df)`**
```python
- Returns rating value ONLY when Charger_Type == 'AC'
- Converts placeholder 'AC' values to NaN
- Returns NaN for non-AC chargers
```

**`extract_dc_charger_rating(df)`**
```python
- Returns rating value ONLY when Charger_Type == 'DC'
- Returns NaN for non-DC chargers
```

### Column Cleaners Added

```python
ColumnCleaner(
    "AC_charger_rating",
    DFDataType.STR,
    column_create_function=extract_ac_charger_rating
),
ColumnCleaner(
    "DC_charger_rating",
    DFDataType.STR,
    column_create_function=extract_dc_charger_rating
),
```

## Results & Statistics

### Charger Type Distribution
| Type | Count |
|------|-------|
| AC | 1,427 |
| DC | 433 |
| Upcoming | 98 |
| **Total** | **1,958** |

### AC Charger Ratings
- **Total AC chargers**: 1,427
- **With extracted ratings**: 905 (63.4%)
- **Without ratings**: 522 (36.6% - missing data in source)

**Top AC Rating Values**:
| Rating | Count |
|--------|-------|
| 22 kW | 647 |
| 6 kW | 112 |
| 7 kW | 70 |
| 11 kW | 31 |
| 19 kW | 14 |
| Others | 31 |

### DC Charger Ratings
- **Total DC chargers**: 433
- **With extracted ratings**: 433 (100%)
- **All DC chargers have defined ratings** ✅

**Top DC Rating Values**:
| Rating | Count |
|--------|-------|
| 50 kW | 87 |
| 75 kW | 80 |
| 25 kW | 52 |
| 175 kW | 46 |
| 150 kW | 44 |
| 125 kW | 19 |
| 130 kW | 16 |
| Others | 99 |

### Upcoming Chargers (Not Yet Built)
- **Count**: 98 stations
- **AC_charger_rating**: NaN (no ratings)
- **DC_charger_rating**: NaN (no ratings)
- Status: Awaiting construction, will be backfilled in Stage 2

## Data Quality Improvements

### Before Splitting
```
Charger_rating (Mixed):
  AC chargers:   "22 kW", "6 kW", "AC" (placeholder), etc.
  DC chargers:   "150 kW", "175 kW", etc.
  Upcoming:      various descriptive values like "2x350kW & 2x175kW"
  
Problem: Can't distinguish AC from DC without referencing Charger_Type
```

### After Splitting
```
AC_charger_rating (AC Only):
  "22 kW" → 22 kW (for AC chargers)
  NaN → (for DC and Upcoming)
  
DC_charger_rating (DC Only):
  "150 kW" → 150 kW (for DC chargers)
  NaN → (for AC and Upcoming)
  
Benefit: Clear, type-specific feature engineering
```

## Feature Characteristics

### AC Charger Ratings
- **Primary range**: 3-23 kW (home/destination charging)
- **Distribution**: Heavily concentrated at 22 kW (45%)
- **Variability**: Low (standardized home charging levels)
- **Missing data**: ~37% (data quality issue)

### DC Charger Ratings
- **Primary range**: 25-250+ kW (fast/rapid charging)
- **Distribution**: Spread across multiple levels
- **Variability**: High (diverse network deployment)
- **Completeness**: 100% (well-maintained data)

## Column Structure

### Original Setup
```
Station_name, Station_address, Charger_Type, Charger_rating, ...
NaN,          "123 Main St",   AC,           "22 kW",        ...
NaN,          "456 Oak St",    DC,           "150 kW",       ...
```

### After Feature Splitting
```
Station_name, Charger_Type, Charger_rating, AC_charger_rating, DC_charger_rating, ...
NaN,          AC,           "22 kW",        "22 kW",           NaN,               ...
NaN,          DC,           "150 kW",       NaN,               "150 kW",          ...
```

## Impact on Downstream Analysis

### Benefits ✅
1. **Cleaner Feature Representation**: No cross-type confusion
2. **Better Analytics**: Can analyze AC vs DC separately
3. **ML Models**: Prevents spurious correlations between unrelated types
4. **Data Validation**: Easy to verify no AC rating in DC column
5. **Interpretability**: Clear which rating applies where

### No Breaking Changes
- Original `Charger_rating` column preserved (still present)
- New columns are additions only
- Existing pipeline code unaffected
- Can use both old and new columns during transition

## Integration with DAG Pipeline

### Step in NSW EV Pipeline
The feature splitting happens automatically when:

```python
1. load_raw_data()
2. clean_data()  ← Feature splitting occurs here via column_create_function
3. validate_data()
4. [other analyses]
```

### Test Output (Real Data)
```
AC chargers with ratings: 905/1427
DC chargers with ratings: 433/433
Upcoming stations: 98 (no ratings)

Sample verification:
  AC charger → AC_charger_rating="22 kW", DC_charger_rating=NaN ✓
  DC charger → AC_charger_rating=NaN, DC_charger_rating="150 kW" ✓
  Upcoming   → AC_charger_rating=NaN, DC_charger_rating=NaN ✓
```

## Future Enhancements

### Phase 1 (Current) ✅
- ✅ Split Charger_rating into AC/DC features
- ✅ Validate feature extraction

### Phase 2 (Recommended)
- 🔲 Numeric conversion: Parse "22 kW" → 22.0 (float)
- 🔲 Unit standardization: Handle variations like "22" vs "22 kW"
- 🔲 Imputation: Fill missing AC ratings using statistical methods

### Phase 3 (Future)
- 🔲 Bin ratings into categories (low/medium/high/ultra)
- 🔲 Calculate coverage metrics by region
- 🔲 Trend analysis: Track AC vs DC deployment over time

## Testing & Validation

### Automated Verification ✅
- Feature extraction runs in DataCleaner pipeline
- Type enforcement: DFDataType.STR
- 1,958 records processed successfully
- No errors or exceptions

### Manual Validation ✅
- AC ratings correctly isolated to AC chargers only
- DC ratings correctly isolated to DC chargers only
- Upcoming chargers have NaN in both new columns
- Original Charger_rating preserved for audit trail

## Summary

**Status**: ✅ Complete and validated

**Impact**: 
- 905 AC chargers with extracted ratings (63.4%)
- 433 DC chargers with extracted ratings (100%)
- 98 upcoming chargers (no ratings yet)

**Quality**: Production-ready, no breaking changes, clean separation of concerns

**Next**: Phase 2 could add numeric conversion and statistical imputation for missing AC ratings
