import random
from os import path

from ptedit import piecetable


corpus = open(path.join(path.dirname(__file__), 'alice1flow.asc')).read()


def random_text():
    src = random.randint(0, len(corpus))
    k = random.binomialvariate(32, 0.125) + 1
    return corpus[src:][:k]


def randomize_point(doc: piecetable.PieceTable):
    offset = random.randint(0, doc.length+1)
    doc.set_point(doc.get_start().move(offset))


def test_soak():
    doc = piecetable.PieceTable(corpus)
    n = 1024
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


