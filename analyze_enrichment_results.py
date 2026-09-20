"""
Advanced analysis of enrichment results.
Generates detailed statistics, visualizations, and insights.
Run this AFTER process_and_enrich_all.py completes.
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from collections import Counter
import re

print("=" * 120)
print("ADVANCED ENRICHMENT ANALYSIS & INSIGHTS")
print("=" * 120)

# Load enriched dataset
print("\nLoading enriched dataset...")
df = pd.read_csv('result_data/all_addresses_enriched.csv')
df_comparison = pd.read_csv('result_data/all_non_detailed_comparison.csv')

print(f"✓ Loaded {len(df)} total addresses")
print(f"✓ Loaded {len(df_comparison)} non-detailed address comparisons")

# ============================================================================
# SECTION 1: OVERALL STATISTICS
# ============================================================================
print("\n" + "=" * 120)
print("1. OVERALL ENRICHMENT STATISTICS")
print("=" * 120)

detailed_count = df['is_detailed'].sum()
non_detailed_count = df['is_non_detailed'].sum()

print(f"\nAddress Classification:")
print(f"  Detailed (already complete):     {detailed_count:4d} ({100*detailed_count/len(df):5.1f}%)")
print(f"  Non-detailed (enriched):         {non_detailed_count:4d} ({100*non_detailed_count/len(df):5.1f}%)")

# Enrichment success
enriched_with_data = df_comparison[df_comparison['enriched'] != '']
fully_enriched = df_comparison[
    (df_comparison['street'] != '') &
    (df_comparison['suburb'] != '') &
    (df_comparison['state'] != '') &
    (df_comparison['postcode'] != '')
]

print(f"\nEnrichment Success:")
print(f"  Successfully enriched:           {len(enriched_with_data):4d} ({100*len(enriched_with_data)/len(df_comparison):5.1f}%)")
print(f"  Fully enriched (4 components):   {len(fully_enriched):4d} ({100*len(fully_enriched)/len(df_comparison):5.1f}%)")
print(f"  Not enriched (no API data):      {len(df_comparison)-len(enriched_with_data):4d} ({100*(len(df_comparison)-len(enriched_with_data))/len(df_comparison):5.1f}%)")

# ============================================================================
# SECTION 2: COMPONENT ANALYSIS
# ============================================================================
print("\n" + "=" * 120)
print("2. COMPONENT-LEVEL ANALYSIS")
print("=" * 120)

has_street = (df_comparison['street'] != '').sum()
has_suburb = (df_comparison['suburb'] != '').sum()
has_state = (df_comparison['state'] != '').sum()
has_postcode = (df_comparison['postcode'] != '').sum()

print(f"\nComponent Completion Rates:")
print(f"  Street names:    {has_street:3d}/{len(df_comparison)} ({100*has_street/len(df_comparison):5.1f}%)")
print(f"  Suburbs:         {has_suburb:3d}/{len(df_comparison)} ({100*has_suburb/len(df_comparison):5.1f}%)")
print(f"  States:          {has_state:3d}/{len(df_comparison)} ({100*has_state/len(df_comparison):5.1f}%)")
print(f"  Postcodes:       {has_postcode:3d}/{len(df_comparison)} ({100*has_postcode/len(df_comparison):5.1f}%)")

# ============================================================================
# SECTION 3: GEOGRAPHIC ANALYSIS
# ============================================================================
print("\n" + "=" * 120)
print("3. GEOGRAPHIC ANALYSIS")
print("=" * 120)

# Top suburbs from enriched data
enriched_suburbs = df_comparison[df_comparison['suburb'] != '']['suburb'].value_counts().head(10)
print(f"\nTop 10 Suburbs (from enriched addresses):")
for i, (suburb, count) in enumerate(enriched_suburbs.items(), 1):
    print(f"  {i:2d}. {suburb:25s} {count:3d} stations")

# Top streets from enriched data
enriched_streets = df_comparison[df_comparison['street'] != '']['street'].value_counts().head(10)
print(f"\nTop 10 Streets (from enriched addresses):")
for i, (street, count) in enumerate(enriched_streets.items(), 1):
    print(f"  {i:2d}. {street:35s} {count:3d} stations")

# ============================================================================
# SECTION 4: IMPROVEMENT METRICS
# ============================================================================
print("\n" + "=" * 120)
print("4. DETAIL IMPROVEMENT METRICS")
print("=" * 120)

# Calculate component counts
def count_components(addr):
    if pd.isna(addr) or addr == '' or addr == 'nan':
        return 0
    return len([p for p in str(addr).split() if p])

df_comparison['original_components'] = df_comparison['original'].apply(count_components)
df_comparison['enriched_components'] = df_comparison['enriched'].apply(count_components)
df_comparison['component_gain'] = df_comparison['enriched_components'] - df_comparison['original_components']

# Only for enriched addresses
enriched_mask = df_comparison['enriched'] != ''

avg_gain = df_comparison[enriched_mask]['component_gain'].mean()
max_gain = df_comparison[enriched_mask]['component_gain'].max()
min_gain = df_comparison[enriched_mask]['component_gain'].min()
total_gain = df_comparison[enriched_mask]['component_gain'].sum()

print(f"\nComponent Addition Statistics:")
print(f"  Average components added:        +{avg_gain:.2f}")
print(f"  Maximum components added:        +{int(max_gain)}")
print(f"  Minimum components added:        +{int(min_gain)}")
print(f"  Total components added:          {int(total_gain)}")

# Length improvement
df_comparison['original_length'] = df_comparison['original'].apply(lambda x: len(str(x)) if pd.notna(x) else 0)
df_comparison['enriched_length'] = df_comparison['enriched'].apply(lambda x: len(str(x)) if pd.notna(x) else 0)
df_comparison['length_gain'] = df_comparison['enriched_length'] - df_comparison['original_length']

avg_length_gain = df_comparison[enriched_mask]['length_gain'].mean()
total_length_gain = df_comparison[enriched_mask]['length_gain'].sum()

print(f"\nCharacter Addition Statistics:")
print(f"  Average characters added:        +{avg_length_gain:.1f}")
print(f"  Total characters added:          +{int(total_length_gain)}")

# ============================================================================
# SECTION 5: BEST & WORST IMPROVEMENTS
# ============================================================================
print("\n" + "=" * 120)
print("5. BEST & WORST IMPROVEMENTS")
print("=" * 120)

# Top improvements
top_5 = df_comparison[enriched_mask].nlargest(5, 'component_gain')
print(f"\nTop 5 Most Improved Addresses (by components added):")
for i, (_, row) in enumerate(top_5.iterrows(), 1):
    print(f"\n  {i}. Gain: +{int(row['component_gain'])} components")
    print(f"     Operator: {row['operator']}")
    print(f"     Original:  '{row['original']}'")
    print(f"     Enriched:  '{row['enriched']}'")

# Least improvements (still enriched)
least_improved = df_comparison[enriched_mask & (df_comparison['component_gain'] >= 0)].nsmallest(5, 'component_gain')
print(f"\n\nLeast Improved (but still enriched):")
for i, (_, row) in enumerate(least_improved.iterrows(), 1):
    print(f"\n  {i}. Gain: +{int(row['component_gain'])} components")
    print(f"     Operator: {row['operator']}")
    print(f"     Original:  '{row['original']}'")
    print(f"     Enriched:  '{row['enriched']}'")

# ============================================================================
# SECTION 6: OPERATOR ANALYSIS
# ============================================================================
print("\n" + "=" * 120)
print("6. OPERATOR ANALYSIS")
print("=" * 120)

# Enrichment rate by operator
df_with_enrichment = df_comparison.copy()
df_with_enrichment['enriched_flag'] = df_with_enrichment['enriched'] != ''

operator_stats = df_with_enrichment.groupby('operator').agg({
    'enriched_flag': ['sum', 'count'],
    'component_gain': 'mean'
}).round(2)

operator_stats.columns = ['enriched', 'total', 'avg_gain']
operator_stats['enrichment_rate'] = (operator_stats['enriched'] / operator_stats['total'] * 100).round(1)
operator_stats = operator_stats.sort_values('enriched', ascending=False).head(10)

print(f"\nTop Operators by Enrichment Count:")
print(f"{'Operator':<25} {'Enriched':<12} {'Total':<8} {'Rate':<8} {'Avg Gain':<10}")
print("-" * 65)
for operator, row in operator_stats.iterrows():
    print(f"{operator:<25} {int(row['enriched']):>8}/{int(row['total']):<2} "
          f"{row['enrichment_rate']:>6.1f}% {row['avg_gain']:>8.1f}")

# ============================================================================
# SECTION 7: COORDINATE QUALITY
# ============================================================================
print("\n" + "=" * 120)
print("7. COORDINATE QUALITY ANALYSIS")
print("=" * 120)

# Check coordinate presence
has_coords = df_comparison['latitude'].notna() & df_comparison['longitude'].notna()
print(f"\nCoordinates for non-detailed addresses:")
print(f"  With coordinates:  {has_coords.sum()}/{len(df_comparison)} ({100*has_coords.sum()/len(df_comparison):.1f}%)")
print(f"  Without coordinates: {(~has_coords).sum()}/{len(df_comparison)} ({100*(~has_coords).sum()/len(df_comparison):.1f}%)")

# Coordinate range
if has_coords.sum() > 0:
    coords_df = df_comparison[has_coords]
    print(f"\nCoordinate Ranges (NSW):")
    print(f"  Latitude:  {coords_df['latitude'].min():.4f} to {coords_df['latitude'].max():.4f}")
    print(f"  Longitude: {coords_df['longitude'].min():.4f} to {coords_df['longitude'].max():.4f}")

# ============================================================================
# SECTION 8: DATA QUALITY SUMMARY
# ============================================================================
print("\n" + "=" * 120)
print("8. DATA QUALITY SUMMARY")
print("=" * 120)

# Original vs Enriched quality metrics
original_empty = (df_comparison['original'] == '').sum()
enriched_empty = (df_comparison['enriched'] == '').sum()

print(f"\nData Completeness:")
print(f"  Empty original addresses:  {original_empty:3d} ({100*original_empty/len(df_comparison):5.1f}%)")
print(f"  Empty enriched addresses:  {enriched_empty:3d} ({100*enriched_empty/len(df_comparison):5.1f}%)")

# Postcode validation
def is_valid_nsw_postcode(pcode):
    if pd.isna(pcode) or pcode == '':
        return False
    try:
        p = int(str(pcode))
        return 2000 <= p <= 2899
    except:
        return False

valid_postcodes = df_comparison[df_comparison['postcode'] != '']['postcode'].apply(is_valid_nsw_postcode).sum()
total_postcodes = (df_comparison['postcode'] != '').sum()

print(f"\nPostcode Validation (NSW range 2000-2899):")
print(f"  Valid postcodes:   {valid_postcodes:3d}/{total_postcodes} ({100*valid_postcodes/total_postcodes:.1f}%)")
print(f"  Invalid/Missing:   {total_postcodes - valid_postcodes:3d}/{total_postcodes}")

# ============================================================================
# SECTION 9: EXPORT ANALYSIS SUMMARY
# ============================================================================
print("\n" + "=" * 120)
print("9. EXPORTING ANALYSIS RESULTS")
print("=" * 120)

# Export sorted by improvement
sorted_df = df_comparison[enriched_mask].sort_values('component_gain', ascending=False)
analysis_file = 'result_data/enrichment_analysis_sorted.csv'
sorted_df.to_csv(analysis_file, index=False)
print(f"  ✓ Sorted analysis: {analysis_file}")

# Export statistics
analysis_summary = pd.DataFrame({
    'Metric': [
        'Total Addresses',
        'Non-detailed Addresses',
        'Successfully Enriched',
        'Enrichment Rate',
        'Fully Enriched (4 components)',
        'Avg Components Added',
        'Avg Characters Added',
        'Street Completion',
        'Suburb Completion',
        'State Completion',
        'Postcode Completion',
        'Addresses with Coordinates',
        'Valid NSW Postcodes',
    ],
    'Value': [
        len(df),
        len(df_comparison),
        len(enriched_with_data),
        f"{100*len(enriched_with_data)/len(df_comparison):.1f}%",
        f"{100*len(fully_enriched)/len(df_comparison):.1f}%",
        f"+{avg_gain:.2f}",
        f"+{avg_length_gain:.1f}",
        f"{100*has_street/len(df_comparison):.1f}%",
        f"{100*has_suburb/len(df_comparison):.1f}%",
        f"{100*has_state/len(df_comparison):.1f}%",
        f"{100*has_postcode/len(df_comparison):.1f}%",
        f"{has_coords.sum()}/{len(df_comparison)}",
        f"{valid_postcodes}/{total_postcodes}",
    ]
})

summary_file = 'result_data/enrichment_analysis_summary.csv'
analysis_summary.to_csv(summary_file, index=False)
print(f"  ✓ Analysis summary: {summary_file}")

print("\n" + "=" * 120)
print("ANALYSIS COMPLETE!")
print("=" * 120)
print(f"\nGenerated files:")
print(f"  1. enrichment_analysis_sorted.csv - All enriched addresses sorted by improvement")
print(f"  2. enrichment_analysis_summary.csv - Summary statistics table")
