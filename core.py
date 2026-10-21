"""Core logic: extract -> validate -> clarify -> export. No UI code here."""
import csv
import io
import json
import os
import re
import time

MODEL = os.getenv("MODEL_NAME", "gemini-3.5-flash-lite")
MAX_TRANSCRIPT_CHARS = 20000  # protects your API credits

SYSTEM_PROMPT = """You are a meeting analyst. Convert the transcript into structured JSON.

Rules:
- Output ONLY valid JSON. No markdown, no commentary.
- Never guess. If an owner or deadline is not stated, use null.
- Owner must be a specific person's name. If the transcript says "someone", "the team" or "everyone", use null.
- Deadline: if a relative date ("by Friday", "next week") can be resolved using the meeting date, output ISO format YYYY-MM-DD. Otherwise output the phrase exactly as spoken. If none, null.
- priority is "high", "medium" or "low" (use "medium" if unclear).
- source_quote is a short snippet (max 20 words) from the transcript backing the task.
- If a task is vague, incomplete or depends on something unclear, set needs_clarification to a short reason. Otherwise null.

Schema:
{
  "summary": "3-5 sentence summary",
  "attendees": ["name"],
  "decisions": [{"decision": "text", "context": "why / short note"}],
  "tasks": [{
    "id": "T1",
    "description": "text",
    "owner": "name or null",
    "deadline": "YYYY-MM-DD, phrase, or null",
    "priority": "high|medium|low",
    "source_quote": "text",
    "needs_clarification": "reason or null"
  }],
  "follow_ups": [{"item": "text", "owner": "name or null", "when": "text or null"}]
}"""

VAGUE_PHRASES = [
    "look into", "look at", "someone should", "we should", "maybe", "try to",
    "figure out", "sort out", "think about", "explore", "as needed", "etc",
]
GENERIC_OWNERS = {"someone", "somebody", "anyone", "everyone", "team", "we", "tbd", "unknown", "n/a", ""}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_client(api_key=None):
    from google import genai
    from google.genai import types
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("No API key found. Set GEMINI_API_KEY or paste it in the sidebar.")
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60000))  # 60 s, then error instead of hanging


def parse_json(text):
    """Parse model output, tolerating code fences or stray text around the JSON."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Model did not return JSON.")
    return json.loads(text[start:end + 1])


def extract(client, transcript, meeting_date=None):
    """Run the LLM extraction and return a normalized result dict."""
    transcript = transcript.strip()
    if not transcript:
        raise ValueError("Transcript is empty.")
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        raise ValueError(f"Transcript too long (max {MAX_TRANSCRIPT_CHARS} characters).")

    from google.genai import types

    user = f"Meeting date: {meeting_date or 'unknown'}\n\nTranscript:\n{transcript}"
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        temperature=0.2,
        max_output_tokens=8192,
    )
    last_err = None
    for attempt in range(4):  # retry on malformed JSON or free-tier rate limits
        try:
            resp = client.models.generate_content(model=MODEL, contents=user, config=config)
            return normalize(parse_json(resp.text))
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
        except Exception as e:
            last_err = e
            if "PerDay" in str(e):
                raise ValueError("Daily free quota for this model is used up. Wait for the reset (often a few hours) or set MODEL_NAME to a different model.") from e
            if any(x in str(e) for x in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "overloaded")):
                time.sleep(10 * (attempt + 1))  # rate limit or busy server: wait and retry
            else:
                raise
    raise ValueError(f"Request failed: {last_err}")


def normalize(result):
    result.setdefault("summary", "")
    result.setdefault("attendees", [])
    result.setdefault("decisions", [])
    result.setdefault("follow_ups", [])
    result.setdefault("tasks", [])
    for i, t in enumerate(result["tasks"], 1):
        t.setdefault("id", f"T{i}")
        for k in ("owner", "deadline", "source_quote", "needs_clarification"):
            t.setdefault(k, None)
        t.setdefault("priority", "medium")
        t.setdefault("description", "")
    return result


def validate(result):
    """Rule-based check. Returns a list of issues, each with a question for the user."""
    issues = []
    for t in result["tasks"]:
        tid = t["id"]
        owner = (t.get("owner") or "").strip().lower()
        deadline = (t.get("deadline") or "").strip()
        desc = (t.get("description") or "").lower()

        if owner in GENERIC_OWNERS:
            issues.append({"task_id": tid, "field": "owner",
                           "issue": "No specific owner",
                           "question": f"Who owns '{t['description']}'?"})
        if not deadline:
            issues.append({"task_id": tid, "field": "deadline",
                           "issue": "No deadline",
                           "question": f"What is the deadline for '{t['description']}'? (YYYY-MM-DD)"})
        elif not ISO_DATE.match(deadline):
            issues.append({"task_id": tid, "field": "deadline",
                           "issue": f"Deadline not a concrete date ('{deadline}')",
                           "question": f"What exact date does '{deadline}' mean for '{t['description']}'? (YYYY-MM-DD)"})
        if any(p in desc for p in VAGUE_PHRASES) or t.get("needs_clarification"):
            reason = t.get("needs_clarification") or "Vague wording"
            issues.append({"task_id": tid, "field": "description",
                           "issue": reason,
                           "question": f"Please state '{t['description']}' as a concrete action. ({reason})"})
    return issues


def apply_clarifications(result, answers):
    """answers: {task_id: {"owner": str, "deadline": str, "description": str}}. Blank values are ignored."""
    by_id = {t["id"]: t for t in result["tasks"]}
    for tid, fields in answers.items():
        task = by_id.get(tid)
        if not task:
            continue
        for field, value in fields.items():
            value = (value or "").strip()
            if value:
                task[field] = value
                if field == "description":
                    task["needs_clarification"] = None
    return result


def tasks_to_csv(result):
    buf = io.StringIO()
    cols = ["id", "description", "owner", "deadline", "priority", "source_quote"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(result["tasks"])
    return buf.getvalue()
