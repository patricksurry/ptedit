import random
from os import path
from enum import IntEnum
from ptedit import document


# use a shortish doc to ensure overlaps
corpus = open(path.join(path.dirname(__file__), 'alice1flow.asc')).read()[:1024]


def random_text():
    src = random.randint(0, len(corpus))
    k = random.binomialvariate(32, 0.125) + 1
    return corpus[src:][:k]


def randomize_point(doc: document.Document):
    # use a binomial around 0 to get lots of action at the ends
    offset = int(random.gauss(0, 128))
    doc.set_point_start().move_point(offset)


class EditType(IntEnum):
    INSERT = 0
    DELETE = 1
    REPLACE = 2


def test_soak():
    doc = document.Document(corpus)
    n = 8192
    random.seed(42)
    for _ in range(n):
        match random.choice(list(EditType)):
            case EditType.INSERT:
                # insert, including empty
                randomize_point(doc)
                doc.insert(random_text())
            case EditType.DELETE:
                # delete fwd/bwd, including zero
                k = random.binomialvariate(64, 0.5) - 32
                randomize_point(doc)
                doc.delete(k)
            case EditType.REPLACE:
                # replace, including empty
                randomize_point(doc)
                doc.replace(random_text())

    # we get about 30% reduction with n=8192 and text=1024 because some edits combine
    assert doc.edit_counts()[1] < n, "expected collapsed edits"
    while doc.has_undo:
        doc.undo()

    assert doc.get_data() == corpus


