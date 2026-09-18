import json
import logging
import re
from typing import List, Dict, Any, Optional
from config import settings
from guardrails import validate_directive_interpretations, parse_time_window

logger = logging.getLogger("llm_interpreter")

SYSTEM_PROMPT = """You are an expert Smart Campus Energy Directive Interpreter for GridWise.
Your job is to read 1 to 3 natural-language operator notes and convert each note into a machine-checkable structured directive JSON entry.

### ALLOWED DIRECTIVE TYPES & REQUIRED STRUCTURED ADJUSTMENTS:
1. `solar_reduction`: Reduce usable solar during specific hours.
   structured_adjustment shape: {"hours": [int, ...], "factor": float}
   NOTE: factor is the fraction of usable solar REMAINING (e.g. "80% reduction" -> factor 0.2; "drop to 20%" -> factor 0.2; "usable solar treated as 25%" -> factor 0.25).

2. `minimum_battery_reserve`: Keep battery energy at or above a required level during specific hours.
   structured_adjustment shape: {"hours": [int, ...], "minimum_energy_kwh": float}

3. `no_charge_window`: Battery charging unavailable during specific hours.
   structured_adjustment shape: {"hours": [int, ...]}

4. `no_discharge_window`: Battery discharging unavailable during specific hours.
   structured_adjustment shape: {"hours": [int, ...]}

5. `max_grid_window`: Grid import capped at stated amount during specific hours.
   structured_adjustment shape: {"hours": [int, ...], "max_grid_kwh": float}

6. `no_op`: Irrelevant note or distractor that does NOT affect today's energy schedule.
   applies MUST be false, directive_type MUST be "no_op", structured_adjustment MUST be null.

### TIME CONVENTIONS:
- Hours are whole-hour intervals from 0 through 23 in ascending order.
- Time windows are start-inclusive and end-exclusive.
  Example: "1 PM to 3 PM" -> hours [13, 14]
  Example: "between 11 AM and 2 PM" -> hours [11, 12, 13] (11 AM = 11, 2 PM = 14)
  Example: "noon until 2 PM" -> hours [12, 13]
  Example: "2 AM to 5 AM" -> hours [2, 3, 4]
  Example: "6 PM until 9 PM" -> hours [18, 19, 20]

### CRITICAL RULES:
- Return a JSON object with a key `directives` containing a JSON array with EXACTLY ONE object per operator note, in note_index order (0, 1, ... N-1).
- Each object MUST contain:
  - `note_index`: integer (0, 1, ...)
  - `applies`: boolean (true for active directives, false ONLY for no_op)
  - `directive_type`: string (one of the 6 allowed types)
  - `structured_adjustment`: object or null (matching required shape)
  - `explanation`: short string explaining the decision.
"""


def call_openai_api(operator_notes: List[str]) -> List[Dict[str, Any]]:
    """Calls OpenAI API using the openai SDK."""
    if not settings.OPENAI_API_KEY:
        logger.warning("No OPENAI_API_KEY found. Falling back.")
        return fallback_rule_parser(operator_notes)

    user_prompt = "Interpret the following operator notes:\n"
    for idx, note in enumerate(operator_notes):
        user_prompt += f"Note {idx}: \"{note}\"\n"
    user_prompt += "\nReturn a JSON object containing a 'directives' array matching the requested schema."

    try:
        import openai
        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        raw_text = response.choices[0].message.content
        logger.info(f"OpenAI LLM Raw Output: {raw_text}")
        data = json.loads(raw_text)
        
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            for k in ["directives", "directive_interpretation", "interpretations", "data"]:
                if k in data and isinstance(data[k], list):
                    return data[k]
            return [data]
    except Exception as e:
        logger.error(f"Error calling OpenAI API: {e}. Falling back to rule parser.")

    return fallback_rule_parser(operator_notes)


def call_gemini_api(operator_notes: List[str]) -> List[Dict[str, Any]]:
    """Calls Gemini API using google-genai or google.generativeai SDK."""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        logger.warning("No GEMINI_API_KEY found in settings. Using fallback rule parser.")
        return fallback_rule_parser(operator_notes)

    user_prompt = f"Interpret the following operator notes:\n"
    for idx, note in enumerate(operator_notes):
        user_prompt += f"Note {idx}: \"{note}\"\n"
    user_prompt += "\nReturn valid JSON array only."

    try:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=settings.MODEL_NAME,
                contents=f"{SYSTEM_PROMPT}\n\n{user_prompt}",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0
                )
            )
            raw_text = response.text
        except Exception:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name=settings.MODEL_NAME,
                system_instruction=SYSTEM_PROMPT
            )
            response = model.generate_content(
                user_prompt,
                generation_config={"response_mime_type": "application/json", "temperature": 0.0}
            )
            raw_text = response.text

        logger.info(f"Gemini LLM Raw Output: {raw_text}")
        data = json.loads(raw_text)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "directive_interpretation" in data:
            return data["directive_interpretation"]
        elif isinstance(data, dict) and "directives" in data:
            return data["directives"]
        elif isinstance(data, dict):
            return [data]
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}. Falling back to rule parser.")

    return fallback_rule_parser(operator_notes)


def call_llm_api(operator_notes: List[str]) -> List[Dict[str, Any]]:
    """Dispatches to OpenAI, Gemini, or Fallback based on provider settings."""
    if settings.LLM_PROVIDER == "openai" or (settings.OPENAI_API_KEY and not settings.GEMINI_API_KEY):
        return call_openai_api(operator_notes)
    elif settings.LLM_PROVIDER == "gemini" or settings.GEMINI_API_KEY:
        return call_gemini_api(operator_notes)
    else:
        return fallback_rule_parser(operator_notes)


def fallback_rule_parser(operator_notes: List[str]) -> List[Dict[str, Any]]:
    """
    Offline heuristic rule parser for local testing and backup operation.
    """
    results = []
    for idx, note in enumerate(operator_notes):
        text = note.lower()

        # Check distractors
        distractor_words = ["cafeteria", "sports office", "registration", "book-return", "library", "club notices", "student affairs", "seminar room"]
        if any(dw in text for dw in distractor_words):
            if not any(k in text for k in ["solar", "battery", "charge", "discharge", "grid", "reserve"]):
                results.append({
                    "note_index": idx,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Irrelevant note; does not affect 24-hour energy schedule."
                })
                continue

        hours = parse_time_window(note)

        # 1. Solar Reduction
        if any(w in text for w in ["solar", "pv", "panel", "cloud cover"]):
            factor = 1.0
            m_pct = re.search(r'(\d+)%', text)
            if m_pct:
                val = float(m_pct.group(1))
                if "drop to" in text or "treated as" in text or "leave roughly" in text or "only" in text:
                    factor = val / 100.0
                elif "reduction" in text or "drop" in text or "cut" in text:
                    factor = (100.0 - val) / 100.0
                else:
                    factor = val / 100.0
            elif "one-fifth" in text:
                factor = 0.2
            elif "half" in text:
                factor = 0.5
            elif "quarter" in text:
                factor = 0.25

            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {"hours": hours, "factor": round(factor, 4)},
                "explanation": f"Solar reduction during hours {hours} with remaining factor {factor}."
            })

        # 2. No Charge Window
        elif any(w in text for w in [
            "no charge", "do not charge", "charger will be isolated",
            "charging is disabled", "charging circuit will be unavailable",
            "charging unavailable", "battery charging is disabled", "cannot charge"
        ]):
            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": hours},
                "explanation": f"Battery charging disabled during hours {hours}."
            })

        # 3. No Discharge Window
        elif any(w in text for w in [
            "no discharge", "do not discharge", "must not discharge",
            "discharging unavailable", "discharging is disabled", "discharge is disabled", "cannot discharge"
        ]):
            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "no_discharge_window",
                "structured_adjustment": {"hours": hours},
                "explanation": f"Battery discharging disabled during hours {hours}."
            })

        # 4. Minimum Battery Reserve
        elif any(w in text for w in [
            "reserve", "keep at least", "minimum energy", "minimum battery",
            "requires at least", "stored in the battery", "remain in the battery"
        ]):
            reserve_val = 0.0
            m_kwh = re.search(r'(\d+(?:\.\d+)?)\s*kwh', text)
            if m_kwh:
                reserve_val = float(m_kwh.group(1))
            else:
                m_pct = re.search(r'(\d+)%\s*of\s*(?:the\s*)?battery', text)
                if m_pct:
                    pct = float(m_pct.group(1))
                    reserve_val = (pct / 100.0) * 200.0

            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "minimum_battery_reserve",
                "structured_adjustment": {"hours": hours, "minimum_energy_kwh": reserve_val},
                "explanation": f"Minimum battery reserve set to {reserve_val} kWh during hours {hours}."
            })

        # 5. Max Grid Window
        elif any(w in text for w in ["grid", "feeder", "transformer", "substation", "intake"]) and any(w in text for w in ["cap", "max", "exceed", "limit", "stay at or below", "not exceed"]):
            m_kwh = re.search(r'(\d+(?:\.\d+)?)\s*kwh', text)
            grid_cap = float(m_kwh.group(1)) if m_kwh else 0.0
            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "max_grid_window",
                "structured_adjustment": {"hours": hours, "max_grid_kwh": grid_cap},
                "explanation": f"Grid import capped at {grid_cap} kWh during hours {hours}."
            })

        else:
            results.append({
                "note_index": idx,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "No matching directive found; treating as no_op."
            })

    return results


def interpret_operator_notes(operator_notes: List[str]) -> List[Any]:
    raw_output = call_llm_api(operator_notes)
    validated = validate_directive_interpretations(raw_output, operator_notes)
    return validated
