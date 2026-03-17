"""Base question type patterns — generic, database-agnostic."""

# Question type patterns — detect what kind of question is being asked
QUESTION_TYPE_PATTERNS = {
    "count": [
        r"\bhow\s+many\b", r"\bcount\b", r"\btotal\b", r"\bnumber\s+of\b",
        r"\bsum\b", r"\baggregate\b",
    ],
    "comparison": [
        r"\bcompare\b", r"\bvs\.?\b", r"\bversus\b", r"\bbetween\b",
        r"\bdifference\b", r"\bmore\s+than\b", r"\bless\s+than\b", r"\bratio\b",
    ],
    "trend": [
        r"\btrend\b", r"\bover\s+time\b", r"\bmonth(ly)?\b", r"\bweek(ly)?\b",
        r"\btime\s*series\b", r"\bhistor(y|ical)\b", r"\bspike\b",
    ],
    "drill_down": [
        r"\bshow\s*(me)?\s*(all)?\b", r"\blist\b", r"\bdisplay\b",
        r"\bwhat\s+(are|is)\b", r"\bwhich\b", r"\bdetails?\b", r"\bbreakdown\b",
    ],
    "audit": [
        r"\baudit\b", r"\bcheck\b", r"\bverify\b", r"\bvalidate\b",
        r"\bmissing\b", r"\bincomplete\b", r"\bdata\s*quality\b",
    ],
    "search": [
        r"\bsearch\b", r"\bfind\b", r"\bwhere\s+is\b", r"\blocate\b",
        r"\blook\s*(for|up)\b",
    ],
}

# Complexity indicators
COMPLEXITY_PATTERNS = {
    "complex": [
        r"\band\s+also\b", r"\bthen\s+show\b", r"\bfor\s+each\b",
        r"\bgroup(ed)?\s+by\b", r"\bper\s+\w+\b",
        r"\bcorrelat\w+\b", r"\bpercent(age)?\b", r"\btop\s+\d+\b",
        r"\bcumulative\b", r"\brolling\b",
    ],
    "moderate": [
        r"\bby\s+\w+\b", r"\bwhere\b.*\band\b",
        r"\baverage\b", r"\bmax\b", r"\bmin\b",
    ],
}
