import re


def parse_salary(raw):
    if not isinstance(raw, str):  # None, or pandas NaN (a float) → no salary
        return {"salary_min": None, "salary_max": None, "salary_period": None}

    text = raw.replace(",", "")
    text = re.sub(r"\d+(?:\.\d+)?%", "", text)  # drop superannuation percentages, not real salary numbers

    if re.search(r"p\.?h\.?\b|per hour|hourly", text, re.IGNORECASE):
        period = "hourly"
    elif re.search(r"p\.?d\.?\b|per day|daily", text, re.IGNORECASE):
        period = "daily"
    else:
        period = "annual"

    # only trust numbers preceded by $/AUD, or part of a dash-separated range — avoids
    # picking up unrelated digits like classification codes (e.g. "AS06")
    range_match = re.search(
        r"(?:\$|AUD)?\s*(\d+(?:\.\d+)?)(k)?\s*(?:[-–]|to)\s*(?:\$|AUD)?\s*(\d+(?:\.\d+)?)(k)?",
        text, re.IGNORECASE
    )
    if range_match:
        v1 = float(range_match.group(1)) * (1000 if range_match.group(2) else 1)
        v2 = float(range_match.group(3)) * (1000 if range_match.group(4) else 1)
        return {"salary_min": min(v1, v2), "salary_max": max(v1, v2), "salary_period": period}

    single_match = re.search(r"(?:\$|AUD)\s*(\d+(?:\.\d+)?)(k)?", text, re.IGNORECASE)
    if single_match:
        v = float(single_match.group(1)) * (1000 if single_match.group(2) else 1)
        return {"salary_min": v, "salary_max": v, "salary_period": period}

    return {"salary_min": None, "salary_max": None, "salary_period": None}


AU_STATES = {"NSW", "VIC", "QLD", "WA", "SA", "ACT", "TAS", "NT"}


def standardise_location(raw):
    """
    Turn messy location text into a clean {city, state}.
    "Norwest, Sydney NSW" -> {city: 'Sydney', state: 'NSW'}
    "Sydney NSW"          -> {city: 'Sydney', state: 'NSW'}
    The city is the segment after the last comma, minus the trailing state code;
    this collapses suburb-prefixed variants onto their parent city.
    """
    if not isinstance(raw, str):
        return {"city": None, "state": None}

    # state = the last state-code token anywhere in the string
    state = None
    for tok in reversed(raw.replace(",", " ").split()):
        if tok.upper() in AU_STATES:
            state = tok.upper()
            break

    # city = last comma-segment with the trailing state code removed
    last_segment = raw.split(",")[-1].strip()
    parts = last_segment.split()
    if parts and parts[-1].upper() in AU_STATES:
        parts = parts[:-1]
    city = " ".join(parts).strip() or None

    return {"city": city, "state": state}


def strip_html(raw):
    """Remove HTML tags and unicode escapes from job description text."""
    if not isinstance(raw, str):  # None, or pandas NaN
        return None
    text = re.sub(r"<[^>]+>", " ", raw)          # remove <strong>, <br>, <li> etc.
    text = text.replace(" ", " ")            # non-breaking spaces → normal spaces
    text = re.sub(r"\s+", " ", text)              # collapse repeated whitespace
    return text.strip()


if __name__ == "__main__":
    print(parse_salary("$60,000 – $70,000 per year"))
    print(parse_salary("$180k – $200k p.a. + Super"))
    print(parse_salary("Competitive salary"))
    print(parse_salary("$60 – $80 p.h. + Super"))
    print(parse_salary("$125,708 per year"))
    print(parse_salary("AUD 150000 – 170000 per annum"))
    print(parse_salary(None))
    print(strip_html("<strong>Role Overview</strong><br>Great job here"))
