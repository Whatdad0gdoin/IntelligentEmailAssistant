"""Dataset rebuilds must never undo a person's work (eval/build_dataset.py).

The human-verified labels are the expensive part of DR-01: someone read every
row. Two tools could quietly lose them. build_enron() used to let a freshly
sampled folder-guess row win an id collision with a human row, and merge()
used to write an unbalanced dataset with only a warning. Both are pinned here.
"""

import csv
import os
import shutil

import pytest

from eval import build_dataset

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval", "data")
COLUMNS = ["id", "provenance", "text_origin", "label_source", "label_confidence", "category",
           "subject", "body", "sender", "received_at", "source_ref"]


def _row(row_id, category, label_source="human", provenance="enron", origin="real"):
    return {"id": row_id, "provenance": provenance, "text_origin": origin,
            "label_source": label_source, "label_confidence": "strong", "category": category,
            "subject": f"s-{row_id}", "body": "b", "sender": "x@example.org",
            "received_at": "", "source_ref": row_id}


def _write(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


# --- build_enron's merge with the file already on disk --------------------------


def test_a_human_label_survives_a_fresh_sample_of_the_same_message():
    existing = [_row("enron-1", "Personal")]                       # a person relabelled it
    fresh = [_row("enron-1", "Work", label_source="folder_heuristic"),
             _row("enron-2", "Work", label_source="folder_heuristic")]
    rows, gave_way = build_dataset.keep_human_rows(fresh, existing)

    by_id = {r["id"]: r for r in rows}
    assert by_id["enron-1"]["category"] == "Personal"
    assert by_id["enron-1"]["label_source"] == "human"
    assert by_id["enron-2"]["label_source"] == "folder_heuristic"   # new message kept
    assert gave_way == 1
    assert len(rows) == 2


def test_only_human_rows_are_carried_across():
    existing = [_row("enron-9", "Work", label_source="folder_heuristic")]
    rows, gave_way = build_dataset.keep_human_rows([], existing)
    assert rows == [] and gave_way == 0


def test_the_committed_enron_file_survives_a_rebuild_unchanged():
    """The real file: every human row comes through with its label, even when
    the fresh sample re-collects every one of them."""
    with open(os.path.join(DATA, "real_enron.csv"), encoding="utf-8") as f:
        existing = list(csv.DictReader(f))
    resampled = [dict(r, label_source="folder_heuristic", category="Work") for r in existing]
    rows, gave_way = build_dataset.keep_human_rows(resampled, existing)
    humans = [r for r in existing if r["label_source"] == "human"]
    assert gave_way == len(humans)
    assert sorted((r["id"], r["category"]) for r in rows) == \
        sorted((r["id"], r["category"]) for r in humans)


# --- merge --------------------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(build_dataset, "DATA", str(tmp_path))
    return tmp_path


def test_merge_refuses_to_write_an_unbalanced_dataset(data_dir):
    _write(data_dir / "real_enron.csv",
           [_row("w1", "Work"), _row("w2", "Work"), _row("p1", "Personal"),
            _row("p2", "Personal"), _row("p3", "Personal")])
    with pytest.raises(SystemExit) as refused:
        build_dataset.merge(per_class=3)
    assert "--per-class 2" in str(refused.value)
    assert not (data_dir / "dataset.csv").exists()


def test_merge_writes_a_balanced_dataset(data_dir):
    _write(data_dir / "real_enron.csv",
           [_row("w1", "Work"), _row("w2", "Work"), _row("p1", "Personal"),
            _row("p2", "Personal"), _row("p3", "Personal")])
    build_dataset.merge(per_class=2)
    with open(data_dir / "dataset.csv", encoding="utf-8") as f:
        written = list(csv.DictReader(f))
    counts = {}
    for row in written:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    assert counts == {"Work": 2, "Personal": 2}


def test_an_unbalanced_dataset_needs_an_explicit_flag(data_dir):
    _write(data_dir / "real_enron.csv", [_row("w1", "Work"), _row("p1", "Personal"),
                                         _row("p2", "Personal")])
    build_dataset.merge(per_class=2, allow_unbalanced=True)
    with open(data_dir / "dataset.csv", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 3


def test_the_documented_rebuild_reproduces_the_committed_dataset(data_dir):
    """`python -m eval.build_dataset --merge --per-class 94` (eval/data/README.md)
    must rebuild exactly the dataset every benchmark since run 10 used."""
    for name in ("real_enron.csv", "real_huggingface.csv", "generated.csv"):
        source = os.path.join(DATA, name)
        if os.path.exists(source):
            shutil.copy(source, data_dir / name)
    build_dataset.merge(per_class=94)
    with open(data_dir / "dataset.csv", encoding="utf-8") as f:
        rebuilt = list(csv.DictReader(f))
    with open(os.path.join(DATA, "dataset.csv"), encoding="utf-8") as f:
        committed = list(csv.DictReader(f))
    assert sorted(r["id"] for r in rebuilt) == sorted(r["id"] for r in committed)
    assert {r["id"]: r["category"] for r in rebuilt} == {r["id"]: r["category"] for r in committed}
