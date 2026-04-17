from app.models import PoliceDepartment


def build_summary(raw_text: str, categories: list[str]) -> str:
    cleaned = " ".join(raw_text.strip().split())
    if len(cleaned) > 220:
        cleaned = f"{cleaned[:217]}..."
    categories_text = ", ".join(categories)
    return f"Gemeldeter Vorfall: {cleaned} | Einstufung: {categories_text}"


def generate_police_script(
    raw_text: str,
    postal_code: str,
    categories: list[str],
    department: PoliceDepartment | None,
) -> str:
    summary = build_summary(raw_text, categories)
    categories_text = ", ".join(categories)
    department_text = (
        f"Zustaendige Dienststelle laut System: {department.name} in {department.city}."
        if department
        else "Es konnte keine zustaendige Dienststelle fuer diese Postleitzahl ermittelt werden."
    )
    return (
        "Guten Tag, hier ist eine automatische Meldung im Auftrag eines Fahrers "
        "des oeffentlichen Nahverkehrs. "
        f"Es wurde folgender Vorfall gemeldet: {summary}. "
        f"Der Vorfall befindet sich im Postleitzahlengebiet {postal_code}. "
        f"Die Situation wurde als {categories_text} eingestuft. "
        f"{department_text} Bitte pruefen Sie den Einsatz und senden Sie bei Bedarf Unterstuetzung."
    )

