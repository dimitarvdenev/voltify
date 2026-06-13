"""Single-shot advisor voice: one LLM call, temp 0, template fallback.

Advisors are real agents (own system prompt, own backend facts) but never
run a tool loop: trigger -> facts -> one narration. The verdict itself is
always computed deterministically by the backend; the LLM only phrases it.
If the model endpoint is down or slow, the template fallback keeps the
demo alive.
"""

import json

from agent import config


def advisor_voice(client, system_prompt, facts, fallback, max_tokens=180):
    """Ask the advisor to narrate its own verdict. Facts are the only
    numbers it may use; on any failure return the deterministic fallback."""
    if client is None:
        return fallback
    try:
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "Verdict facts (the only numbers you may state):\n"
                        + json.dumps(facts, separators=(",", ":"))
                        + "\n\nNarrate this verdict to the control room in "
                        "2-3 sentences. State only numbers present in the "
                        "facts. Do not invent values, do not add options "
                        "beyond those in the facts."
                    ),
                },
            ],
            temperature=0,
            max_tokens=max_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or fallback
    except Exception:
        return fallback
