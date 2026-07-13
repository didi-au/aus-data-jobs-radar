"""
Tests for the salary parser and HTML stripper.
Each test pins down one of the salary 'shapes' we found in the real data,
so if the parser ever changes and breaks a case, these fail loudly.
"""
import sys
from pathlib import Path

# make transform/ importable regardless of where pytest is run from
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "transform"))

from parsers import parse_salary, strip_html, standardise_location


# ---- salary: clean annual ranges ----
def test_annual_range_endash():
    r = parse_salary("$130,000 – $150,000 per year")
    assert r["salary_min"] == 130000
    assert r["salary_max"] == 150000
    assert r["salary_period"] == "annual"


def test_annual_range_hyphen():
    r = parse_salary("$150,000-$160,000 package + salary packaging")
    assert r["salary_min"] == 150000
    assert r["salary_max"] == 160000


def test_annual_range_word_to():
    # the 'to' separator, not just dashes
    r = parse_salary("$160,000 to $190,000 per year plus super")
    assert r["salary_min"] == 160000
    assert r["salary_max"] == 190000


# ---- salary: 'k' shorthand ----
def test_k_shorthand():
    r = parse_salary("$180k – $200k p.a. + Super")
    assert r["salary_min"] == 180000
    assert r["salary_max"] == 200000


# ---- salary: AUD prefix, no dollar sign ----
def test_aud_prefix():
    r = parse_salary("AUD 150000 – 170000 per annum")
    assert r["salary_min"] == 150000
    assert r["salary_max"] == 170000


# ---- salary: single value → min == max ----
def test_single_value():
    r = parse_salary("$125,708 per year")
    assert r["salary_min"] == 125708
    assert r["salary_max"] == 125708


# ---- salary: hourly kept raw, period labelled (not converted) ----
def test_hourly_kept_raw():
    r = parse_salary("AUD 75 - 100 per hour")
    assert r["salary_min"] == 75
    assert r["salary_max"] == 100
    assert r["salary_period"] == "hourly"


def test_daily_kept_raw():
    r = parse_salary("$800 – $840 p.d.")
    assert r["salary_period"] == "daily"


# ---- salary: no number at all → all None ----
def test_marketing_text_no_number():
    r = parse_salary("Competitive salary")
    assert r["salary_min"] is None
    assert r["salary_max"] is None


def test_none_input():
    r = parse_salary(None)
    assert r["salary_min"] is None
    assert r["salary_period"] is None


# ---- salary: superannuation % must not be mistaken for a salary number ----
def test_super_percentage_ignored():
    r = parse_salary("$97,148 – $133,968 plus 15.4% superannuation")
    assert r["salary_min"] == 97148
    assert r["salary_max"] == 133968


# ---- location standardisation ----
def test_location_plain_city():
    r = standardise_location("Sydney NSW")
    assert r["city"] == "Sydney"
    assert r["state"] == "NSW"


def test_location_suburb_collapses_to_city():
    # the whole point: suburb-prefixed variants roll up to the parent city
    r = standardise_location("Norwest, Sydney NSW")
    assert r["city"] == "Sydney"
    assert r["state"] == "NSW"


def test_location_melbourne_suburb():
    r = standardise_location("Tullamarine, Melbourne VIC")
    assert r["city"] == "Melbourne"
    assert r["state"] == "VIC"


def test_location_none():
    r = standardise_location(None)
    assert r["city"] is None
    assert r["state"] is None


# ---- HTML stripping ----
def test_strip_html_tags():
    assert strip_html("<strong>Role</strong><br>Great job") == "Role Great job"


def test_strip_html_none():
    assert strip_html(None) is None
