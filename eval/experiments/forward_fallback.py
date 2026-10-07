"""Forward fallback: classify forwards and replies on their content, not their subject.

    python -m eval.experiments.forward_fallback --model gpt-4o-mini --split dev

THE PROBLEM
preprocess() cuts every body at the first quoted-history or forwarded-message
marker, which is right for a reply ("the new part is what the user needs") and
wrong for a bare forward, where the forwarded message IS the content. 30 of the
376 dataset emails (8%) come out of preprocessing with fewer than 40 characters
of body, 26 of them FW/Fwd/RE messages, so the classifier sees little more than
the subject line. Every model is measurably worse on those rows.

THE CHANGE UNDER TEST
When the cleaned body is shorter than MIN_CHARS, fall back to the body with the
quoted/forwarded history kept (HTML still stripped, signature still cut,
whitespace normalised, same character budget). Everything else is unchanged.
The evidence verifier checks quotes against exactly the text the model was
given, because the patched function feeds both -- so a quote taken from the
forwarded part verifies, and nothing is checked against text the model never
saw.

PROTOCOL
Runs one email per call so that only the near-empty rows receive a different
input; it is paired with '<model>+unbatched' from eval/experiments/knn_fewshot
(k=0), which differs from this run in nothing else. Decide on dev, then run
test once. Applied inside this process only -- backend/ is not modified.
"""

import argparse

from backend.orchestrator import classify as classify_module
from backend.orchestrator import preprocess as preprocess_module
from eval import compare_models

MIN_CHARS = 40


def _with_fallback(original):
    def preprocess(raw_body, budget_chars, is_html=None, label=""):
        cleaned = original(raw_body, budget_chars, is_html=is_html, label=label)
        if len(cleaned.text.strip()) >= MIN_CHARS:
            return cleaned
        raw_body = raw_body or ""
        html = preprocess_module.looks_like_html(raw_body) if is_html is None else is_html
        text = preprocess_module.html_to_text(raw_body) if html else raw_body
        text = preprocess_module.normalise_whitespace(text)
        text = preprocess_module.strip_signature(text)       # quoted history kept
        text = preprocess_module.normalise_whitespace(text)
        text, truncated = preprocess_module.truncate_from_top(text, budget_chars)
        if len(text.strip()) <= len(cleaned.text.strip()):
            return cleaned
        return preprocess_module.Preprocessed(text=text, original_chars=len(raw_body),
                                              final_chars=len(text), truncated=truncated)
    return preprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--tag", default="r1")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    patched = _with_fallback(preprocess_module.preprocess)
    # Both names are imported into their modules, so both must be patched: the
    # classifier builds its prompt and its verifier source from the first, the
    # harness recomputes the verifier source for its reason column from the second.
    classify_module.preprocess = patched
    compare_models.preprocess = patched

    compare_models.run_classify(
        args.model, args.split, args.tag, args.force, batch_size=1,
        run_name=f"{args.model}+unbatched-fwd",
        extra_settings={"forward_fallback_min_chars": MIN_CHARS})


if __name__ == "__main__":
    main()
