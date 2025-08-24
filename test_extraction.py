#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for accountant name extraction functionality
"""

import re
import unicodedata

# ASCII-only regex; special punctuation normalized beforehand
ACC_REGEX = re.compile(r'רו["\']?ח[:\s\-]+(.+?)(?:[,;|()\[\]{}]|\s-\s| עבור|$)')

def normalize_text(text: str) -> str:
    """
    Normalize Hebrew text by handling special quotes and dashes.
    """
    if not isinstance(text, str):
        return ""

    normalized = unicodedata.normalize('NFKC', text)

    replacements = {
        # Dashes
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        # Double quotes
        "\u201C": '"',
        "\u201D": '"',
        "\u05F4": '"',
        # Single quotes
        "\u2018": "'",
        "\u2019": "'",
        "\u05F3": "'",
    }

    for src, dst in replacements.items():
        normalized = normalized.replace(src, dst)

    return normalized.strip()

def extract_accountant(description):
    """
    Extract accountant name from payment description
    Returns the accountant name or "לא מזוהה" if not found
    """
    if not isinstance(description, str):
        return "לא מזוהה"

    normalized_desc = normalize_text(description)
    match = ACC_REGEX.search(normalized_desc)

    if match:
        accountant_name = match.group(1).strip()
        accountant_name = re.sub(r'^\s*[-]\s*', '', accountant_name)
        accountant_name = re.sub(r'\s+', ' ', accountant_name)
        return accountant_name if accountant_name else "לא מזוהה"

    return "לא מזוהה"

def test_extraction():
    """Test the accountant extraction with various examples"""

    test_cases = [
        ("ליווי עוסק מורשה גבייה עבור - רו\"ח אלכס פבזנר (משהו...)", "אלכס פבזנר"),
        ("רו\"ח משה כהן - עבור", "משה כהן"),
        ("תשלום עבור רו\"ח שרה לוי", "שרה לוי"),
        ("רו\"ח דוד כהן עבור", "דוד כהן"),
        ("ליווי עבור רו\"ח יוסי לוי - תשלום", "יוסי לוי"),
        ("רו\"ח אנה שמואלי", "אנה שמואלי"),
        ("תשלום רו\"ח יעקב כהן עבור שירותים", "יעקב כהן"),
        # Different quote types
        ("רו״ח דן לוי", "דן לוי"),
        ("רו'ח רות כהן", "רות כהן"),
        # Separators
        ("רו\"ח אבי שמואלי, עבור", "אבי שמואלי"),
        ("רו\"ח מיכל לוי; תשלום", "מיכל לוי"),
        ("רו\"ח יוסי כהן | עבור", "יוסי כהן"),
        # No match
        ("תשלום עבור שירותים", "לא מזוהה"),
        ("ליווי עוסק מורשה", "לא מזוהה"),
        ("", "לא מזוהה"),
        (None, "לא מזוהה"),
        ("רו\"ח", "לא מזוהה"),
    ]

    print("🧪 Testing Accountant Name Extraction")
    print("=" * 50)

    passed = 0
    failed = 0

    for i, (input_text, expected) in enumerate(test_cases, 1):
        result = extract_accountant(input_text)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        print(f"{i:2d}. {status}")
        print(f"    Input:  {input_text}")
        print(f"    Expected: {expected}")
        print(f"    Got:      {result}\n")
        if result == expected:
            passed += 1
        else:
            failed += 1

    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")

if __name__ == "__main__":
    test_extraction()
