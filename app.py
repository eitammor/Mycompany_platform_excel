# -*- coding: utf-8 -*-
"""
Simple Flask app:
- Frontend: single upload page (Hebrew)
- Backend: receives one Excel (.xlsx), keeps specific Hebrew columns,
  extracts accountant name as everything AFTER the last dash ('-') or after 'רו"ח' in "תיאור התשלום",
  routes rows in two phases (auto, then manual overrides), groups by accountant,
  writes one Excel per accountant, zips them, and returns the ZIP for download.
"""

import io
import re
import zipfile
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np
from flask import Flask, render_template, request, send_file, jsonify
from flask_cors import CORS
from rapidfuzz import fuzz
import unicodedata

app = Flask(__name__)
CORS(app)

# ===== Configuration =====

# Required columns (exact order)
REQUIRED_COLUMNS = [
    "חודש חיוב",
    "תאריך חיוב",
    "שם העסק",
    "שם",
    "משפחה",
    "אימייל",
    "טלפון",
    "סוג עסקה",
    "סוג תשלום",
    "סכום",
    "עמלת אשראי",
    "מע\"מ",
    "להעברה",
    "תיאור התשלום",
]

FUZZY_THRESHOLD = 90

# Person → core accountant name (NO 'רו"ח' prefix)
CLEAN_MANUAL_MAP: Dict[str, str] = {
    "שיר אקרמן": "דורון פלק",
    "יובל בן סירה": "שחר שולץ",
    "אופיר וינוגרד": "יוחאי כחלון",
    "אילן מיצ'ניק": "אלכס פבזנר",
    "אייל סעד": "דורון פלק",
    "עשהאל מימוני": "אהרון פארדו",
    "רונאל בלאיש": "אסף גונן",
    "טל זילברמן": "שחר שולץ",
    "איתן קזז": "אהרון פארדו",
    "אייל אמוץ": "אסף גונן",
    "עקיבא גליקמן": "אלכס פבזנר",
    "ולדימיר שייגנדרוב": "אסף גונן",
    "שייגנדרוב": "אסף גונן",
    "ולדימיר": "אסף גונן",
    "אורית וידל": "אילן קאופמן",
    "ויטל חיים נהרדעה": "חיים יעקובזון",  # Added mapping
    "ויטל נהרדעה": "חיים יעקובזון",  # Alternative variant
    "ויטל חיים": "חיים יעקובזון",  # Another variant
}

# Business names that should be excluded (legal services, not accountant services)
EXCLUDED_BUSINESSES = {
    "אי.די סייבר סולושנס",
    "אי די סייבר סולושנס",
    "ID Cyber Solutions",
    "I.D Cyber Solutions",
}

# Columns to sum in the totals row
SUM_COLS = ["סכום", "עמלת אשראי", "מע\"מ", "להעברה"]
# First textual column to host the totals label
LABEL_CANDIDATES = ["תיאור התשלום", "שם העסק", "שם"]


# ===== Normalization helpers =====

def normalize_quotes_and_dashes(text: str) -> str:
    """Normalize only quotes and dash variants to ASCII. Keep everything else intact."""
    if not isinstance(text, str):
        return ""
    s = unicodedata.normalize("NFKC", text)
    replacements = {
        # Dashes
        "\u2012": "-",  # figure dash
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2015": "-",  # horizontal bar
        "\u2212": "-",  # minus sign
        # Double quotes
        "\u201C": '"',
        "\u201D": '"',
        "\u05F4": '"',  # Hebrew gershayim
        # Single quotes
        "\u2018": "'",
        "\u2019": "'",
        "\u05F3": "'",  # Hebrew geresh
    }
    for src, dst in replacements.items():
        s = s.replace(src, dst)
    return s


def normalize_text(text: str) -> str:
    """
    Heavy normalization used for fuzzy/substring matching:
    - NFKC
    - Unify quotes/dashes
    - Keep only Hebrew/English letters, digits, spaces, quotes and dash
    - Collapse spaces and trim
    """
    if not isinstance(text, str):
        return ""
    s = normalize_quotes_and_dashes(text)
    s = re.sub(r'[^0-9A-Za-z\u0590-\u05FF\s\'"-]+', ' ', s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_excluded_business(row) -> bool:
    """Check if the business name is in the excluded list."""
    business_name = str(row.get("שם העסק", "")).strip()
    if not business_name:
        return False
    
    # Normalize for comparison
    business_norm = normalize_text(business_name)
    for excluded in EXCLUDED_BUSINESSES:
        if normalize_text(excluded) == business_norm:
            return True
    return False


# ===== Extraction from description =====

def extract_accountant_after_dash(description: str) -> str:
    """
    Extract everything after the LAST '-' or after 'רו"ח' in the payment description.
    If nothing found, return the trimmed string (or 'לא מזוהה' if empty).
    """
    if not isinstance(description, str):
        return "לא מזוהה"
    s = normalize_quotes_and_dashes(description)

    last_dash = s.rfind("-")
    last_word = s.rfind('רו"ח')
    cut_index = max(last_dash, last_word)

    if cut_index != -1:
        right = s[cut_index + 1 :].strip()
    else:
        right = s.strip()

    return right if right else "לא מזוהה"


# ===== Manual mapping helpers =====

def get_person_raw(row) -> str:
    """Build person name from first + last name columns."""
    first = str(row.get("שם", "")).strip()
    last = str(row.get("משפחה", "")).strip()
    if first and last:
        return f"{first} {last}"
    elif first:
        return first
    elif last:
        return last
    else:
        return ""


def find_core_for_person(person_raw: str) -> str:
    """Find the core accountant name for a person (from manual mapping)."""
    if not person_raw:
        return ""
    person_norm = normalize_text(person_raw)
    
    # Check all possible matches
    for person, core in CLEAN_MANUAL_MAP.items():
        person_map_norm = normalize_text(person)
        # Check exact match
        if person_map_norm == person_norm:
            return core
        # Check if the mapped person is contained in the raw person (for partial matches)
        if person_map_norm in person_norm or person_norm in person_map_norm:
            return core
    return ""


def resolve_target_full_name(core_target: str, phase1_full_names: List[str]) -> str:
    """
    Resolve a core target (like 'אהרון פארדו') to a full name that matches
    one of the phase1 candidates, or synthesize a new one.
    """
    if not core_target:
        return "לא מזוהה"
    
    # Try to find an exact match in phase1 candidates
    for candidate in phase1_full_names:
        if core_target in candidate or candidate in core_target:
            return candidate
    
    # If no match found, synthesize a full name
    if not core_target.startswith('רו"ח'):
        return f'רו"ח {core_target}'
    else:
        return core_target


# ===== Fuzzy merging =====

def fuzzy_merge_names(names: List[str]) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, List[str]]]:
    """
    Fuzzy merge similar names.
    Returns:
    - map_orig_to_canon: original → canonical
    - map_orig_to_norm: original → normalized
    - groups: canonical → list of originals
    """
    if not names:
        return {}, {}, {}
    
    # Normalize all names
    norm_to_orig = defaultdict(list)
    for name in names:
        norm = normalize_text(name)
        norm_to_orig[norm].append(name)
    
    # Find similar normalized names
    norm_names = list(norm_to_orig.keys())
    groups = {}
    processed = set()
    
    for i, norm1 in enumerate(norm_names):
        if norm1 in processed:
            continue
            
        similar = [norm1]
        processed.add(norm1)
        
        for norm2 in norm_names[i+1:]:
            if norm2 in processed:
                continue
                
            # Check similarity
            ratio = fuzz.ratio(norm1, norm2)
            if ratio >= FUZZY_THRESHOLD:
                similar.append(norm2)
                processed.add(norm2)
        
        # Use the longest normalized name as canonical
        canonical_norm = max(similar, key=len)
        canonical_orig = max(norm_to_orig[canonical_norm], key=len)
        
        groups[canonical_orig] = []
        for norm in similar:
            groups[canonical_orig].extend(norm_to_orig[norm])
    
    # Build mappings
    map_orig_to_canon = {}
    map_orig_to_norm = {}
    
    for canonical, originals in groups.items():
        for orig in originals:
            map_orig_to_canon[orig] = canonical
            map_orig_to_norm[orig] = normalize_text(orig)
    
    return map_orig_to_canon, map_orig_to_norm, groups


# ===== Excel helpers =====

def add_totals_row(df: pd.DataFrame) -> pd.DataFrame:
    """Add a totals row at the end of the dataframe."""
    if df.empty:
        return df
    
    # Find the first textual column for the label
    label_col = None
    for col in LABEL_CANDIDATES:
        if col in df.columns:
            label_col = col
            break
    
    if label_col is None:
        label_col = df.columns[0]
    
    # Calculate sums for numeric columns
    totals = {}
    for col in SUM_COLS:
        if col in df.columns:
            totals[col] = df[col].sum()
    
    # Create totals row
    totals_row = pd.Series(index=df.columns, dtype=object)
    totals_row[label_col] = "סה\"כ"
    for col, value in totals.items():
        totals_row[col] = value
    
    # Append totals row
    return pd.concat([df, pd.DataFrame([totals_row])], ignore_index=True)


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for ZIP entry."""
    # Remove or replace problematic characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove leading/trailing spaces and dots
    sanitized = sanitized.strip('. ')
    return sanitized


# ===== Flask routes =====

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "לא נבחר קובץ"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "לא נבחר קובץ"}), 400
        
        if not file.filename.endswith('.xlsx'):
            return jsonify({"error": "רק קבצי Excel (.xlsx) נתמכים"}), 415
        
        print(f"Processing file: {file.filename}")
        
        # Read Excel file
        df = pd.read_excel(file, engine="openpyxl")
        print(f"Loaded {len(df)} rows, {len(df.columns)} columns")
        
        # Validate required columns
        missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
        if missing:
            return jsonify({"error": "חסרות עמודות נדרשות: " + ", ".join(missing)}), 400

        # Keep only required columns in exact order
        df = df[REQUIRED_COLUMNS].copy()

        # Remove rows with empty payment description
        if "תיאור התשלום" in df.columns:
            df = df[df["תיאור התשלום"].notna()]
            df = df[df["תיאור התשלום"].str.strip() != ""]

        # Filter out excluded businesses (legal services)
        excluded_mask = df.apply(is_excluded_business, axis=1)
        excluded_rows = df[excluded_mask]
        if not excluded_rows.empty:
            print(f"Excluding {len(excluded_rows)} rows from excluded businesses:")
            for _, row in excluded_rows.iterrows():
                print(f"  - {row['שם העסק']}: {row.get('שם', '')} {row.get('משפחה', '')}")
        
        df = df[~excluded_mask].copy()
        print(f"Continuing with {len(df)} rows after exclusions")

        # Build person name used for manual mapping
        df["person_raw"] = df.apply(get_person_raw, axis=1)

        # --- Phase split by manual mapping
        df["core_target"] = df["person_raw"].apply(find_core_for_person)

        # Debug: Print manual mappings
        manual_mappings = df[df["core_target"] != ""][["person_raw", "core_target"]]
        if not manual_mappings.empty:
            print("Manual mappings found:")
            for _, row in manual_mappings.iterrows():
                print(f"  {row['person_raw']} -> {row['core_target']}")

        df_phase1 = df[df["core_target"] == ""].copy()   # NOT mapped → normal flow
        df_phase2 = df[df["core_target"] != ""].copy()   # mapped → forced target

        # Phase 1: detect accountant from description, fuzzy merge
        if not df_phase1.empty:
            df_phase1["accountant_raw"] = df_phase1["תיאור התשלום"].apply(extract_accountant_after_dash)
            df_phase1["accountant_norm"] = df_phase1["accountant_raw"].apply(normalize_text)

            originals = df_phase1["accountant_raw"].tolist()
            map_orig_to_canon, map_orig_to_norm, _ = fuzzy_merge_names(originals)
            df_phase1["accountant_canonical"] = df_phase1["accountant_raw"].map(map_orig_to_canon)
            df_phase1["accountant_final"] = df_phase1["accountant_canonical"]

        # Phase 1 candidates (full names we already produced)
        phase1_full_names = (
            sorted(df_phase1["accountant_final"].dropna().unique().tolist())
            if not df_phase1.empty else []
        )

        # Phase 2: map core target to a real full name (or synthesize)
        if not df_phase2.empty:
            print(f"Phase 1 candidates: {phase1_full_names}")
            df_phase2["accountant_final"] = df_phase2["core_target"].apply(
                lambda core: resolve_target_full_name(core, phase1_full_names)
            )
            print("Phase 2 final mappings:")
            for _, row in df_phase2[["person_raw", "core_target", "accountant_final"]].drop_duplicates().iterrows():
                print(f"  {row['person_raw']} -> {row['core_target']} -> {row['accountant_final']}")

        # Merge both phases
        if not df_phase1.empty or not df_phase2.empty:
            df_final = pd.concat([x for x in [df_phase1, df_phase2] if not x.empty], ignore_index=True)
        else:
            df_final = df.copy()

        # Ensure numerics for summaries/mapping
        for col in SUM_COLS:
            if col in df_final.columns:
                df_final[col] = pd.to_numeric(df_final[col], errors="coerce")

        # Prepare ZIP
        print("Preparing ZIP file...")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Variants that should be merged into a single Ilan-Kaufman file
            ILAN_DISPLAY_VARIANTS = {
                'רו"ח אילן קאופמן',
                'ו״ח אילן קאופמן',
                'רו"ח_אילן_קאופמן',
                'ו״ח_אילן_קאופמן',
                'ליווי משפטי',
                'ליווי עוסק מורשה',
                'ליווי עוסק פטור',
            }
            ILAN_TARGET_ZIP_NAME = 'רו״ח אילן קאופמן.xlsx'

            # Variants that should be merged into a single Aaron Pardo file
            AARON_DISPLAY_VARIANTS = {
                'רו"ח אהרון פארדו',
                'רו"ח אהרון פרדו',
                'רו״ח אהרון פארדו',
                'רו״ח אהרון פרדו',
                'אהרון פארדו',
                'אהרון פרדו',
            }
            AARON_TARGET_ZIP_NAME = 'רו״ח אהרון פארדו.xlsx'

            ilan_parts = []
            aaron_parts = []

            # Group and process accountants
            grouped = df_final.groupby("accountant_final")
            
            for acc_name, group in grouped:
                group_data = group[REQUIRED_COLUMNS].copy()

                # Normalize the accountant name for comparison
                acc_normalized = normalize_text(acc_name)
                
                # Check for Ilan variants
                is_ilan = False
                for variant in ILAN_DISPLAY_VARIANTS:
                    if normalize_text(variant) == acc_normalized:
                        is_ilan = True
                        break
                
                # Check for Aaron variants
                is_aaron = False
                if "אהרון" in acc_name and ("פארדו" in acc_name or "פרדו" in acc_name):
                    is_aaron = True
                else:
                    for variant in AARON_DISPLAY_VARIANTS:
                        if normalize_text(variant) == acc_normalized:
                            is_aaron = True
                            break

                if is_ilan:
                    # Collect for Ilan merge; don't write individual files
                    ilan_parts.append(group_data)
                    print(f"  Adding to Ilan merge: {acc_name} ({len(group_data)} rows)")
                    continue

                if is_aaron:
                    # Collect for Aaron merge; don't write individual files
                    aaron_parts.append(group_data)
                    print(f"  Adding to Aaron merge: {acc_name} ({len(group_data)} rows)")
                    continue

                # Normal path - write individual file
                group_data = add_totals_row(group_data)
                excel_buf = io.BytesIO()
                with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
                    group_data.to_excel(writer, index=False, sheet_name="Sheet1")
                excel_buf.seek(0)
                zf.writestr(f"{sanitize_filename(acc_name)}.xlsx", excel_buf.getvalue())
                print(f"  Writing individual file: {sanitize_filename(acc_name)}.xlsx ({len(group_data)-1} rows)")

            # Write merged Ilan file (if any)
            if ilan_parts:
                ilan_df = pd.concat(ilan_parts, ignore_index=True)
                ilan_df = add_totals_row(ilan_df)
                excel_buf = io.BytesIO()
                with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
                    ilan_df.to_excel(writer, index=False, sheet_name="Sheet1")
                excel_buf.seek(0)
                zf.writestr(ILAN_TARGET_ZIP_NAME, excel_buf.getvalue())
                print(f"Created merged Ilan file with {len(ilan_parts)} groups, {len(ilan_df)-1} total rows")

            # Write merged Aaron file (if any)
            if aaron_parts:
                aaron_df = pd.concat(aaron_parts, ignore_index=True)
                aaron_df = add_totals_row(aaron_df)
                excel_buf = io.BytesIO()
                with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
                    aaron_df.to_excel(writer, index=False, sheet_name="Sheet1")
                excel_buf.seek(0)
                zf.writestr(AARON_TARGET_ZIP_NAME, excel_buf.getvalue())
                print(f"Created merged Aaron file with {len(aaron_parts)} groups, {len(aaron_df)-1} total rows")

            # Keep mapping summaries as-is
            df_final["source"] = np.where(df_final.get("core_target", "") != "", "manual", "auto")

            # Consolidate variants in the summary
            df_summary = df_final.copy()
            
            # Consolidate Ilan variants
            ilan_mask = df_summary["accountant_final"].isin(ILAN_DISPLAY_VARIANTS)
            df_summary.loc[ilan_mask, "accountant_final"] = 'רו״ח אילן קאופמן'

            # Consolidate Aaron variants
            aaron_mask = (df_summary["accountant_final"].str.contains("אהרון", na=False) & 
                         (df_summary["accountant_final"].str.contains("פארדו", na=False) | 
                          df_summary["accountant_final"].str.contains("פרדו", na=False)))
            df_summary.loc[aaron_mask, "accountant_final"] = 'רו״ח אהרון פארדו'

            # Create summary by accountant
            summary_by_accountant = (
                df_summary.groupby(["accountant_final", "source"], as_index=False)
                        .agg(
                            rows=("תיאור התשלום", "count"),
                            amount_sum=("סכום", "sum"),
                            fee_sum=("עמלת אשראי", "sum"),
                            vat_sum=("מע\"מ", "sum"),
                            transfer_sum=("להעברה", "sum"),
                        )
            )
            csv1 = io.BytesIO()
            csv1.write('\ufeff'.encode('utf-8'))
            summary_by_accountant.to_csv(csv1, index=False, encoding="utf-8")
            csv1.seek(0)
            zf.writestr("mapping_summary_by_accountant.csv", csv1.getvalue())

            # Create manual mappings summary
            mapped_people = (
                df_summary[df_summary["source"] == "manual"]
                [["person_raw", "accountant_final"]]
                .drop_duplicates()
                .rename(columns={"person_raw": "person", "accountant_final": "target_accountant"})
            )
            csv2 = io.BytesIO()
            csv2.write('\ufeff'.encode('utf-8'))
            mapped_people.to_csv(csv2, index=False, encoding="utf-8")
            csv2.seek(0)
            zf.writestr("mapping_people_manual.csv", csv2.getvalue())

            # Add excluded businesses report if any were excluded
            if not excluded_rows.empty:
                excluded_summary = excluded_rows[["שם העסק", "שם", "משפחה", "תיאור התשלום"]].copy()
                excluded_summary["סיבת אי הכללה"] = "שירות משפטי - לא שירות רו״ח"
                csv3 = io.BytesIO()
                csv3.write('\ufeff'.encode('utf-8'))
                excluded_summary.to_csv(csv3, index=False, encoding="utf-8")
                csv3.seek(0)
                zf.writestr("excluded_businesses.csv", csv3.getvalue())
                print(f"Added excluded businesses report with {len(excluded_rows)} rows")

        zip_buffer.seek(0)
        print("ZIP file prepared successfully, returning to client")
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name='דוחות-רו"ח.zip',
            etag=False
        )

    except Exception as e:
        print(f"General error in upload_file: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"שגיאה כללית: {str(e)}"}), 500


if __name__ == "__main__":
    # Bind to 0.0.0.0:7860 for local development
    app.run(host="0.0.0.0", port=7860, debug=False)