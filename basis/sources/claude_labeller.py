import hashlib
import json

import anthropic
from psycopg.types.json import Jsonb

MODEL = "claude-opus-5"
EFFORT = "medium"
MAX_TOKENS = 8000

LABELLER_ID = "claude"

"""
The version pins the model, the prompt and the schema together. Any change to
one of them is a change of measurement, so it takes a new version rather than
overwriting the old rows, and the whole history has to be relabelled before the
new version is used in a study. Live and historical labels that disagree about
what they mean are worse than no labels.
"""
LABELLER_VERSION = "policy-language-1"
FEATURE_KEY = "fomc_policy_language"

CHARACTERISATION = ["easing", "elevated", "rising", "not_characterised"]

"""
Structured outputs accept a narrow slice of JSON Schema. Every object carries
additionalProperties false and lists every property as required, the nullable
field is written with anyOf rather than as a list of types, and nothing here
uses a length or numeric constraint. A schema the API rejects would otherwise
be discovered on the first paid call over a corpus of 58 documents.
"""
SCHEMA = {
    "type": "object",
    "properties": {
        "policy_action": {
            "type": "string",
            "enum": ["hike", "cut", "hold", "not_stated"],
        },
        "action_size_bps": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "dissent_count": {"type": "integer"},
        "dissent_directions": {
            "type": "array",
            "items": {"type": "string", "enum": ["tighter", "easier", "other"]},
        },
        "inflation_language": {"type": "string", "enum": CHARACTERISATION},
        "labor_language": {
            "type": "string",
            "enum": ["strong", "moderating", "weakening", "not_characterised"],
        },
        "growth_language": {
            "type": "string",
            "enum": ["solid", "moderate", "slowing", "not_characterised"],
        },
        "forward_guidance": {
            "type": "string",
            "enum": ["explicit_path", "data_dependent", "none"],
        },
        "balance_sheet_mentioned": {"type": "boolean"},
        "risk_balance": {
            "type": "string",
            "enum": [
                "balanced",
                "tilted_to_inflation",
                "tilted_to_employment",
                "not_stated",
            ],
        },
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["field", "quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "policy_action",
        "action_size_bps",
        "dissent_count",
        "dissent_directions",
        "inflation_language",
        "labor_language",
        "growth_language",
        "forward_guidance",
        "balance_sheet_mentioned",
        "risk_balance",
        "evidence",
    ],
    "additionalProperties": False,
}

"""
Two rules carry the honesty of this labeller.

Every field must be supported by a verbatim quote from the document. A label
that cannot cite the text is a label the model produced from somewhere else,
and for statements published between 2023 and 2026 that somewhere else is very
likely its own training data, which knows what the market did next.

And the task is extraction, not judgement. There is no hawkish or dovish field
here on purpose: that reading is exactly where hindsight would enter. What the
statement said about inflation is checkable; whether it was a surprise is for
the statistics to decide from price.
"""
PROMPT = """You are extracting structured attributes from a Federal Open Market
Committee document. Work only from the text supplied below.

Rules:
- Every field you fill must be supported by wording actually present in the
  document. Put the supporting verbatim quote in the evidence array, one entry
  per field you did not answer with a "not_stated" or "not_characterised" value.
- Do not use anything you know about this meeting, the market's reaction, later
  meetings, or what happened afterwards. If the document does not say it, the
  answer is the "not_stated" or "not_characterised" option.
- Do not judge whether the document is hawkish or dovish. That reading is not
  wanted here and is not one of the fields.
- action_size_bps is the size of the change to the target range in basis points,
  positive for a hike and negative for a cut, and null when the document states
  no change or does not state one.
- dissent_count counts committee members recorded as voting against the action.

Document:
<document>
{body}
</document>"""


def input_digest(body: str) -> str:
    """
    Hashes exactly what determined the answer: the model, the prompt, the
    schema and the document. A changed digest on an unchanged version is the
    signal that something drifted without anyone bumping the version.
    """
    material = json.dumps(
        {
            "model": MODEL,
            "effort": EFFORT,
            "prompt": PROMPT,
            "schema": SCHEMA,
            "body": body,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def request_params(body: str) -> dict:
    """
    The single place a request is described, so the dry run shows exactly what
    a paid run would send rather than an approximation of it.
    """
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "output_config": {
            "effort": EFFORT,
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
        "messages": [{"role": "user", "content": PROMPT.format(body=body)}],
    }


def label(body: str, client: anthropic.Anthropic | None = None) -> dict:
    client = client or anthropic.Anthropic()

    response = client.messages.create(**request_params(body))

    if response.stop_reason == "refusal":
        raise RuntimeError(
            "the labeller was declined by a safety classifier: "
            f"{getattr(response.stop_details, 'category', None)}"
        )
    if response.stop_reason == "max_tokens":
        raise RuntimeError("the label was cut off, raise MAX_TOKENS")

    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def unlabelled(conn, document_type: str | None = None) -> list[dict]:
    return conn.execute(
        """
        select d.id, d.document_key, d.document_type, d.published_at, d.body
        from basis.text_document d
        where (%s::text is null or d.document_type = %s)
          and not exists (
              select 1 from basis.text_feature f
              where f.document_id = d.id
                and f.feature_key = %s
                and f.labeller_id = %s
                and f.labeller_version = %s
          )
        order by d.published_at
        """,
        (document_type, document_type, FEATURE_KEY, LABELLER_ID, LABELLER_VERSION),
    ).fetchall()


def features_as_of(conn, as_of, event_key: str | None = None) -> list[dict]:
    """
    The reader the study will use. A label is reachable from the instant its
    document was published and not from the instant it was computed, so a
    backfill run today is legitimately visible to a backtest of 2023 while a
    document published after the cutoff stays invisible.
    """
    return conn.execute(
        """
        select d.event_key, d.document_type, d.published_at, f.value,
               f.labeller_version
        from basis.text_feature f
        join basis.text_document d on d.id = f.document_id
        where f.feature_key = %s and f.labeller_id = %s
          and f.labeller_version = %s
          and f.available_at <= %s
          and (%s::text is null or d.event_key = %s)
        order by d.published_at
        """,
        (
            FEATURE_KEY, LABELLER_ID, LABELLER_VERSION, as_of,
            event_key, event_key,
        ),
    ).fetchall()


def store(conn, document: dict, value: dict) -> int:
    """
    available_at mirrors the document's publication and never the instant this
    ran. The reasoning existed the moment the text was public; the labeller only
    records when someone got around to reading it.
    """
    result = conn.execute(
        """
        insert into basis.text_feature
          (document_id, feature_key, labeller_id, labeller_version,
           input_sha256, available_at, value)
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (document_id, feature_key, labeller_id, labeller_version)
        do nothing
        """,
        (
            document["id"],
            FEATURE_KEY,
            LABELLER_ID,
            LABELLER_VERSION,
            input_digest(document["body"]),
            document["published_at"],
            Jsonb(value),
        ),
    )
    return result.rowcount
