"""The review CLI's blind second read (eval/review_cli.py).

382 of the first 383 human verdicts accepted the model's proposal unchanged,
on a tool that showed the proposal first. The blind mode exists so a second
person can label without that anchor, and the agreement report says how far
the two reads actually agree.
"""

import csv
import sys

import pytest

from eval import review_cli

FIELDS = ["row", "verified", "proposed_category", "confidence", "rationale",
          "sender", "subject", "body_preview", "id"]


def _review_file(path, verdicts):
    rows = [{"row": str(i), "verified": v, "proposed_category": p, "confidence": "strong",
             "rationale": "model reason", "sender": "a@corp.com", "subject": f"s{i}",
             "body_preview": "preview", "id": f"enron-{i}"}
            for i, (v, p) in enumerate(verdicts, 1)]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_kappa_is_one_for_perfect_agreement_and_lower_for_chance():
    rows = [{"verified": "y", "proposed_category": "Work", "blind_k": "Work"},
            {"verified": "Personal", "proposed_category": "Work", "blind_k": "Personal"}]
    assert review_cli.agreement(rows, "blind_k")["kappa"] == pytest.approx(1.0)

    rows = [{"verified": "y", "proposed_category": "Work", "blind_k": "Personal"},
            {"verified": "y", "proposed_category": "Personal", "blind_k": "Work"}]
    stats = review_cli.agreement(rows, "blind_k")
    assert stats["observed"] == 0.0 and stats["kappa"] < 0


def test_unanswered_rows_are_left_out_of_agreement():
    rows = [{"verified": "y", "proposed_category": "Work", "blind_k": ""},
            {"verified": "", "proposed_category": "Work", "blind_k": "Work"}]
    assert review_cli.agreement(rows, "blind_k") is None


def test_the_blind_read_never_touches_the_first_verdicts(tmp_path, monkeypatch, capsys):
    path = tmp_path / "review_work_new.csv"
    _review_file(path, [("y", "Work"), ("Personal", "Work")])
    answers = iter(["", "2", "1"])   # Enter is not an answer in blind mode
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(review_cli, "full_bodies", lambda: {})
    monkeypatch.setattr(sys, "argv", ["review_cli", "--category", "Work", "--file", str(path),
                                      "--blind", "--annotator", "kevin"])
    review_cli.main()

    rows = _read(path)
    assert [r["verified"] for r in rows] == ["y", "Personal"]          # untouched
    assert [r["blind_kevin"] for r in rows] == ["Personal", "Work"]
    shown = capsys.readouterr().out
    assert "Model proposes" not in shown and "model reason" not in shown


def test_full_bodies_include_the_candidate_pool(tmp_path, monkeypatch):
    pool = tmp_path / "pool.csv"
    with open(pool, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "body"])
        writer.writeheader()
        writer.writerow({"id": "enron-new", "body": "The whole body, not a preview."})
    monkeypatch.setattr(review_cli, "POOL_PATH", str(pool))
    monkeypatch.setattr(review_cli, "ENRON_PATH", str(tmp_path / "missing.csv"))
    assert review_cli.full_bodies() == {"enron-new": "The whole body, not a preview."}
