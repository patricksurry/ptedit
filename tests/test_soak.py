from ptedit import document
from .random_soak import random_soak, corpus, apply_actions


def test_soak():
    # use a shortish doc to ensure overlaps
    n = 1024
    steps = 8192

    doc = document.Document(corpus[:n])
    apply_actions(doc, random_soak(steps, 42))

    # we get about 60% reduction with n=8192 and text=1024 because some edits combine
    assert doc.edit_counts()[1] < 0.5 * steps, "expected collapsed edits"
    while doc.has_undo:
        doc.undo()

    assert doc.get_data() == corpus[:n]


