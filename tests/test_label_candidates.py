"""The human-review tooling must not lose or duplicate work (eval/label_candidates.py).

Two hazards found on 2026-10-06. --build wrote straight over review_<category>.csv,
and review_work.csv is the only record of the 120 Work decisions people already
made. --apply de-duplicated by id only, but one candidate is an existing test
row's message under a different id, so applying it would have put the same
email in the dataset twice.
"""

import csv
import json

import pytest

from eval import label_candidates as lc

BODY_FIELDS = ["row", "id", "sender", "subject", "body", "source_ref"]
ENRON_FIELDS = ["id", "provenance", "text_origin", "label_source", "label_confidence", "category",
                "subject", "body", "sender", "received_at", "source_ref"]


def _csv(path, fields, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def pool(tmp_path, monkeypatch):
    """A tiny candidate pool, label file and real_enron.csv in a temp folder."""
    monkeypatch.setattr(lc, "DATA", str(tmp_path))
    monkeypatch.setattr(lc, "BODIES", str(tmp_path / "personal_candidates_bodies.csv"))
    monkeypatch.setattr(lc, "ENRON_PATH", str(tmp_path / "real_enron.csv"))
    monkeypatch.setattr(lc, "LABELS_PATH", str(tmp_path / "proposed_labels.json"))
    _csv(tmp_path / "personal_candidates_bodies.csv", BODY_FIELDS, [
        {"row": "1", "id": "enron-new", "sender": "a@corp.com", "subject": "Q3 pipeline",
         "body": "Please send the pipeline numbers.", "source_ref": "maildir/a/inbox/1."},
        {"row": "2", "id": "enron-dupe", "sender": "b@corp.com", "subject": "Gas desk",
         "body": "Desk update.", "source_ref": "maildir/cash-m/inbox/112."},
    ])
    with open(tmp_path / "proposed_labels.json", "w", encoding="utf-8") as f:
        json.dump({"enron-new": ["Work", "strong", "a task"],
                   "enron-dupe": ["Work", "strong", "a task"]}, f)
    _csv(tmp_path / "real_enron.csv", ENRON_FIELDS, [
        {"id": "enron-existing", "provenance": "enron", "text_origin": "real",
         "label_source": "human", "label_confidence": "strong", "category": "Work",
         "subject": "Gas desk", "body": "Desk update.", "sender": "b@corp.com",
         "received_at": "", "source_ref": "maildir/cash-m/inbox/112."},
    ])
    return tmp_path


def test_build_refuses_to_overwrite_a_file_holding_verdicts(pool):
    _csv(pool / "review_work.csv", lc.REVIEW_FIELDS,
         [{"row": "9", "verified": "y", "proposed_category": "Work", "id": "enron-x"}])
    with pytest.raises(SystemExit) as refused:
        lc.build("Work")
    assert "--out" in str(refused.value)
    with open(pool / "review_work.csv", encoding="utf-8") as f:
        assert list(csv.DictReader(f))[0]["verified"] == "y"     # untouched


def test_build_can_write_a_new_review_file_alongside(pool):
    _csv(pool / "review_work.csv", lc.REVIEW_FIELDS,
         [{"row": "9", "verified": "y", "proposed_category": "Work", "id": "enron-x"}])
    lc.build("Work", out=str(pool / "review_work_new.csv"))
    with open(pool / "review_work_new.csv", encoding="utf-8") as f:
        assert {r["id"] for r in csv.DictReader(f)} == {"enron-new"}


def test_build_may_replace_an_unreviewed_file(pool):
    _csv(pool / "review_work.csv", lc.REVIEW_FIELDS,
         [{"row": "9", "verified": "", "proposed_category": "Work", "id": "enron-x"}])
    lc.build("Work")
    with open(pool / "review_work.csv", encoding="utf-8") as f:
        assert {r["id"] for r in csv.DictReader(f)} == {"enron-new"}


def _more_work_candidates(pool, count):
    """Add `count` fresh Work candidates, each from its own sender and subject."""
    with open(pool / "personal_candidates_bodies.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(pool / "proposed_labels.json", encoding="utf-8") as f:
        labels = json.load(f)
    for i in range(count):
        rows.append({"row": str(10 + i), "id": f"enron-more-{i}", "sender": f"s{i}@corp.com",
                     "subject": f"Budget item {i}", "body": "Please approve.",
                     "source_ref": f"maildir/m/inbox/{i}."})
        labels[f"enron-more-{i}"] = ["Work", "strong", "a task"]
    _csv(pool / "personal_candidates_bodies.csv", BODY_FIELDS, rows)
    with open(pool / "proposed_labels.json", "w", encoding="utf-8") as f:
        json.dump(labels, f)


def test_limit_writes_a_short_batch_in_pool_order(pool):
    """Six more Work rows should not mean reading every candidate the pool has:
    --apply needs every row in the file decided."""
    _more_work_candidates(pool, 5)
    lc.build("Work", out=str(pool / "batch.csv"), limit=3)
    with open(pool / "batch.csv", encoding="utf-8") as f:
        assert [r["id"] for r in csv.DictReader(f)] == ["enron-new", "enron-more-0", "enron-more-1"]


def test_a_candidate_already_in_the_dataset_is_not_offered_again(pool):
    """So a second batch picks up after the first, rather than repeating it."""
    _more_work_candidates(pool, 2)
    with open(pool / "real_enron.csv", encoding="utf-8") as f:
        existing = list(csv.DictReader(f))
    existing.append({**existing[0], "id": "enron-new", "source_ref": "maildir/a/inbox/1."})
    _csv(pool / "real_enron.csv", ENRON_FIELDS, existing)
    lc.build("Work", out=str(pool / "batch2.csv"), limit=1)
    with open(pool / "batch2.csv", encoding="utf-8") as f:
        assert [r["id"] for r in csv.DictReader(f)] == ["enron-more-0"]


def test_apply_skips_a_message_already_in_the_dataset_under_another_id(pool):
    lc.build("Work", out=str(pool / "review_work_new.csv"))
    with open(pool / "review_work_new.csv", encoding="utf-8") as f:
        review = list(csv.DictReader(f))
    for row in review:
        row["verified"] = "y"
    _csv(pool / "review_work_new.csv", lc.REVIEW_FIELDS, review)

    lc.apply("Work", review_file=str(pool / "review_work_new.csv"))
    with open(pool / "real_enron.csv", encoding="utf-8") as f:
        ids = [r["id"] for r in csv.DictReader(f)]
    assert "enron-new" in ids
    assert "enron-dupe" not in ids                 # same message as enron-existing
    assert ids.count("enron-existing") == 1
