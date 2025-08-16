import random
from os import path

from ptedit import piecetable


# use a shortish doc to ensure overlaps
corpus = open(path.join(path.dirname(__file__), 'alice1flow.asc')).read()[:1024]


def random_text():
    src = random.randint(0, len(corpus))
    k = random.binomialvariate(32, 0.125) + 1
    return corpus[src:][:k]


def randomize_point(doc: piecetable.PieceTable):
    # use a binomial around 0 to get lots of action at the ends
    offset = int(random.gauss(0, 128))
    doc.set_point(doc.get_start().move(offset))


def test_soak():
    doc = piecetable.PieceTable(corpus)
    n = 8192
    random.seed(42)
    for _ in range(n):
        match random.randint(0, 3):
            case 0:
                # insert, including empty
                randomize_point(doc)
                doc.insert(random_text())
            case 1:
                # delete fwd/bwd, including zero
                k = random.binomialvariate(64, 0.5) - 32
                randomize_point(doc)
                doc.delete(k)
            case 2:
                # replace, including empty
                randomize_point(doc)
                doc.replace(random_text())

    for _ in range(n):
        doc.undo()

    assert doc.data == corpus


