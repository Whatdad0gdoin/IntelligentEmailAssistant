"""JSON schemas for structured model output (spec section 4.1).

Every call constrains the response with one of these. Nothing in this codebase
parses prose or runs a regex over model output to find a field -- if the schema
does not describe it, we do not read it.

The category enum here is the mechanism behind section 4.3: the model cannot
return a fifth category because the schema will not let it. "Review" is
deliberately absent -- it is a destination the *backend* assigns when a label
fails verification, never a value the model can choose for itself.

Structured-output note: OpenAI strict mode supports a subset of JSON Schema. It
enforces types, required fields and enums, but not minItems/maxItems or numeric
bounds. Count and range constraints are therefore enforced in Python, which is
what the spec asks for anyway ("enforce the count programmatically, not by
asking the model nicely").
"""

# The four categories the classifier may return.
CATEGORIES = ("Work", "Personal", "Promotions", "Studies")

# The fifth bucket. Assigned by grounding.py, never by the model.
REVIEW_CATEGORY = "Review"

# Voice intents (section 6.3). "unknown" is a required, valid outcome.
INTENTS = ("summarise", "read", "draft", "unknown")

# Section 3: summary must be 2 or 3 sentences. Enforced in summarise.py.
SUMMARY_MIN_SENTENCES = 2
SUMMARY_MAX_SENTENCES = 3


CLASSIFY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["results"],
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "category", "confidence", "evidence"],
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "The id supplied with the email. Copy it exactly.",
                    },
                    "category": {
                        "type": "string",
                        "enum": list(CATEGORIES),
                    },
                    "confidence": {
                        "type": "number",
                        "description": "0.0 to 1.0. Be honest: a low value routes the email to human review, which is the correct outcome when unsure.",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "A short span copied WORD FOR WORD from the email body or subject that justifies this category. It is checked against the source; an invented span discards the label.",
                    },
                },
            },
        }
    },
}


SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "action_items"],
    "properties": {
        "summary": {
            "type": "array",
            "description": "Exactly 2 or 3 complete sentences.",
            "items": {"type": "string"},
        },
        "action_items": {
            "type": "array",
            "description": "Concrete things the reader must do. Empty when the email asks for nothing.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "source_sentence"],
                "properties": {
                    "text": {"type": "string"},
                    "source_sentence": {
                        "type": "integer",
                        "description": "1-based index of the summary sentence this came from.",
                    },
                },
            },
        },
    },
}


DRAFT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["draft"],
    "properties": {
        "draft": {
            "type": "string",
            "description": "The reply body as plain text, including a greeting and sign-off.",
        }
    },
}


INTENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "target_reference", "confidence"],
    "properties": {
        "intent": {
            "type": "string",
            "enum": list(INTENTS),
        },
        "target_reference": {
            "type": "string",
            "description": "The words in the transcript naming which email, copied verbatim (for example 'the one from Sarah'). Empty string when the user did not say.",
        },
        "confidence": {
            "type": "number",
            "description": "0.0 to 1.0. Use 'unknown' with low confidence rather than guessing.",
        },
    },
}
