from collections import defaultdict


FALLBACK_CATEGORY_KEY = "unclear_disruption"

# Deterministic keyword map: category key -> phrases/keywords
KEYWORD_RULES: dict[str, list[str]] = {
    "traffic_accident": [
        "unfall",
        "zusammenstoss",
        "zusammenstoß",
        "angefahren",
        "kollision",
        "zusammenprall",
    ],
    "illegal_parking_blocking": [
        "falsch geparkt",
        "falschparker",
        "blockiert",
        "steht im weg",
        "spur blockiert",
        "gleis blockiert",
    ],
    "physical_altercation": [
        "schlaegt",
        "schlägt",
        "pruegelt",
        "prügelt",
        "kampf",
        "koerperliche auseinandersetzung",
        "körperliche auseinandersetzung",
    ],
    "harassment": [
        "belaestigt",
        "belästigt",
        "sexuell",
        "anschreit",
        "beleidigt",
        "bedraengt",
        "bedrängt",
    ],
    "vandalism": [
        "vandalismus",
        "schmierei",
        "grafitti",
        "graffiti",
        "mutwillig zerstoert",
        "mutwillig zerstört",
    ],
    "medical_emergency": [
        "notfall",
        "bewusstlos",
        "verletzt",
        "blutet",
        "krampfanfall",
        "atemnot",
    ],
    "threat": [
        "bedroht",
        "droht",
        "messer",
        "waffe",
        "gewalt androht",
    ],
    "property_damage": [
        "sachbeschaedigung",
        "sachbeschädigung",
        "scheibe eingeschlagen",
        "fenster zerbrochen",
        "sitz beschaedigt",
    ],
    "theft": [
        "diebstahl",
        "gestohlen",
        "taschendieb",
        "geraubt",
        "geklaut",
    ],
    "operational_disruption": [
        "stoerung",
        "störung",
        "betriebsablauf",
        "verspaetung durch vorfall",
        "verspätung durch vorfall",
        "fahrt unterbrochen",
    ],
}


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def detect_category_keys(text: str) -> list[str]:
    normalized = normalize_text(text)
    scores: dict[str, int] = defaultdict(int)

    for category_key, keywords in KEYWORD_RULES.items():
        for keyword in keywords:
            if keyword in normalized:
                # Phrase matches count slightly higher than single-token matches.
                weight = 2 if " " in keyword else 1
                scores[category_key] += weight

    if not scores:
        return [FALLBACK_CATEGORY_KEY]

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [category_key for category_key, _ in ranked]

