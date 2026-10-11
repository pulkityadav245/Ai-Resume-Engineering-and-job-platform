"""India-specific helpers: canonical city names (with common aliases) for filtering and ingestion."""
import re

CITIES: dict[str, list[str]] = {
    "Bengaluru": ["bengaluru", "bangalore"], "Hyderabad": ["hyderabad", "secunderabad"],
    "Pune": ["pune"], "Mumbai": ["mumbai", "navi mumbai", "thane", "bombay"],
    "Delhi": ["delhi", "new delhi"], "Gurugram": ["gurugram", "gurgaon"],
    "Noida": ["noida", "greater noida"], "Chennai": ["chennai"], "Kolkata": ["kolkata", "calcutta"],
    "Ahmedabad": ["ahmedabad"], "Chandigarh": ["chandigarh", "mohali", "panchkula"],
    "Jaipur": ["jaipur"], "Indore": ["indore"], "Kochi": ["kochi", "cochin", "ernakulam"],
    "Coimbatore": ["coimbatore"], "Thiruvananthapuram": ["thiruvananthapuram", "trivandrum"],
    "Nagpur": ["nagpur"], "Lucknow": ["lucknow"], "Bhubaneswar": ["bhubaneswar"],
    "Dehradun": ["dehradun"], "Vadodara": ["vadodara", "baroda"], "Visakhapatnam": ["visakhapatnam", "vizag"],
    "Mysuru": ["mysuru", "mysore"], "Remote": ["remote", "work from home", "wfh"],
}
# default ingestion order: biggest tech hiring hubs first ("Remote" is not sent to providers)
INGEST_CITIES = ["Bengaluru", "Hyderabad", "Pune", "Mumbai", "Delhi", "Gurugram", "Noida", "Chennai",
                 "Kolkata", "Ahmedabad", "Chandigarh", "Jaipur", "Indore", "Kochi", "Dehradun"]
_PATTERNS = [(canon, re.compile(r"\b(?:%s)\b" % "|".join(map(re.escape, aliases))))
             for canon, aliases in CITIES.items()]


def normalize_city(location: str | None) -> str | None:
    s = (location or "").lower()
    for canon, pat in _PATTERNS:
        if pat.search(s):
            return canon
    return None
