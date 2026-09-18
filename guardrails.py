import re
from typing import List, Dict, Any, Optional
from schemas import DirectiveInterpretation


ALLOWED_DIRECTIVES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
}


def sanitize_hours(hours: Any) -> List[int]:
    """Ensures hours is a list of unique integers 0..23 in ascending order."""
    if not isinstance(hours, list):
        return []
    cleaned = set()
    for h in hours:
        try:
            val = int(h)
            if 0 <= val <= 23:
                cleaned.add(val)
        except (ValueError, TypeError):
            continue
    return sorted(list(cleaned))


def validate_and_clean_directive(
    raw_item: Dict[str, Any],
    note_index: int,
    original_note: str
) -> DirectiveInterpretation:
    """
    Validates and cleans a raw directive interpretation against Problem Statement guardrails.
    """
    directive_type = str(raw_item.get("directive_type", "no_op")).lower().strip()
    if directive_type not in ALLOWED_DIRECTIVES:
        directive_type = "no_op"

    explanation = str(raw_item.get("explanation", "")).strip()
    if not explanation:
        explanation = f"Processed note {note_index}"

    if directive_type == "no_op":
        return DirectiveInterpretation(
            note_index=note_index,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation=explanation or "This note does not affect today's 24-hour energy schedule."
        )

    # For all non-no_op directives, applies MUST be true
    raw_adj = raw_item.get("structured_adjustment")
    if not isinstance(raw_adj, dict):
        return DirectiveInterpretation(
            note_index=note_index,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="Invalid adjustment structure returned; defaulting to no_op."
        )

    hours = sanitize_hours(raw_adj.get("hours", []))
    if not hours and directive_type != "no_op":
        return DirectiveInterpretation(
            note_index=note_index,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="No valid hours specified; defaulting to no_op."
        )

    cleaned_adj: Dict[str, Any] = {"hours": hours}

    if directive_type == "solar_reduction":
        try:
            factor = float(raw_adj.get("factor", 1.0))
            factor = max(0.0, min(1.0, factor))
            cleaned_adj["factor"] = round(factor, 4)
        except (ValueError, TypeError):
            cleaned_adj["factor"] = 1.0

    elif directive_type == "minimum_battery_reserve":
        try:
            val = float(raw_adj.get("minimum_energy_kwh", 0.0))
            cleaned_adj["minimum_energy_kwh"] = round(max(0.0, val), 4)
        except (ValueError, TypeError):
            cleaned_adj["minimum_energy_kwh"] = 0.0

    elif directive_type == "max_grid_window":
        try:
            val = float(raw_adj.get("max_grid_kwh", 0.0))
            cleaned_adj["max_grid_kwh"] = round(max(0.0, val), 4)
        except (ValueError, TypeError):
            cleaned_adj["max_grid_kwh"] = 0.0

    elif directive_type in ("no_charge_window", "no_discharge_window"):
        pass

    return DirectiveInterpretation(
        note_index=note_index,
        applies=True,
        directive_type=directive_type, # type: ignore
        structured_adjustment=cleaned_adj,
        explanation=explanation
    )


def validate_directive_interpretations(
    raw_interpretations: List[Dict[str, Any]],
    operator_notes: List[str]
) -> List[DirectiveInterpretation]:
    num_notes = len(operator_notes)
    by_index: Dict[int, Dict[str, Any]] = {}

    for item in raw_interpretations:
        if isinstance(item, dict):
            idx = item.get("note_index")
            if isinstance(idx, int) and 0 <= idx < num_notes:
                by_index[idx] = item

    results: List[DirectiveInterpretation] = []
    for i in range(num_notes):
        raw_item = by_index.get(i)
        if not raw_item:
            result = DirectiveInterpretation(
                note_index=i,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation="No interpretation provided for note; default to no_op."
            )
        else:
            result = validate_and_clean_directive(raw_item, i, operator_notes[i])
        results.append(result)

    return results


def parse_time_window(text: str) -> List[int]:
    """
    Regex-based time window parser helper for whole-hour start-inclusive, end-exclusive windows.
    """
    text_lower = text.lower()

    # Pattern 1: 24h format e.g. "13:00 to 15:00" or "13:00-15:00"
    match_24 = re.search(r'(\d{1,2}):00\s*(?:to|-|until|and)\s*(\d{1,2}):00', text_lower)
    if match_24:
        start, end = int(match_24.group(1)), int(match_24.group(2))
        if 0 <= start < end <= 24:
            return list(range(start, end))

    # Normalize 'noon' -> '12 PM', 'midnight' -> '12 AM'
    normalized = text_lower.replace("noon", "12 pm").replace("midnight", "12 am")

    # Pattern 2: "1 PM to 3 PM", "from 10 AM until 12 PM", "2 AM until 5 AM", "between 11 AM and 2 PM"
    match_12 = re.search(
        r'(?:from|between)?\s*(\d{1,2})\s*(am|pm)?\s*(?:to|-|until|and)\s*(\d{1,2})\s*(am|pm)',
        normalized
    )
    if match_12:
        h1 = int(match_12.group(1))
        p1 = match_12.group(2)
        h2 = int(match_12.group(3))
        p2 = match_12.group(4)

        if not p1:
            p1 = p2  # e.g. "1 to 3 PM" -> both PM

        start = _to_24h(h1, p1)
        end = _to_24h(h2, p2)
        if 0 <= start < end <= 24:
            return list(range(start, end))

    return []


def _to_24h(hour: int, period: str) -> int:
    period = period.lower() if period else ""
    if period == "pm" and hour < 12:
        return hour + 12
    if period == "am" and hour == 12:
        return 0
    return hour
