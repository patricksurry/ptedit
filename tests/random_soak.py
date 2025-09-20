import random
from os import path
from enum import IntEnum

from ptedit import document

corpus = open(path.join(path.dirname(__file__), 'alice1flow.asc')).read()


class EditType(IntEnum):
    MOVE = 0
    INSERT = 1
    DELETE = 2
    REPLACE = 3


def random_text() -> str:
    start = random.randint(0, len(corpus))
    k = random.binomialvariate(32, 0.125) + 1
    return corpus[start:][:k]


Action = tuple[EditType, int, str]


def random_action(typ: EditType) -> Action:
    s = random_text() if typ in (EditType.INSERT, EditType.REPLACE) else ''
    match typ:
        case EditType.MOVE:
            # use a binomial around 0 to get lots of action at the ends
            k = int(random.gauss(0, 128))
        case EditType.DELETE:
            k = random.binomialvariate(64, 0.5) - 32
        case _:
            k = 0
    return (typ, k, s)


def random_soak(n: int, seed: int = 42) -> list[Action]:
    random.seed(seed)
    return [
        random_action(typ) for typ in random.choices(
            [EditType.MOVE, EditType.INSERT, EditType.DELETE, EditType.REPLACE],
            weights=[4,2,2,2],
            k=n
        )
    ]


def apply_actions(doc: document.Document, actions: list[Action]) -> document.Document:
    for (typ, k, s) in actions:
        match typ:
            case EditType.MOVE:
                doc.set_point_start().move_point(k)
            case EditType.INSERT:
                doc.insert(s)
            case EditType.DELETE:
                doc.delete(k)
            case EditType.REPLACE:
                doc.replace(s)
    return doc



if __name__ == '__main__':
    import argparse, json

    parser = argparse.ArgumentParser(
        prog='random_soak',
        description='Generate a random soak test'
    )

    parser.add_argument('-s', '--steps', help='Number of steps', default=16)
    parser.add_argument('-n', '--length', help='Length of initial document', default=128)
    parser.add_argument('-f', '--forth', help='Generate forth code', action='store_true')

    args = parser.parse_args()

    actions = random_soak(args.steps)

    doc = document.Document(corpus[:args.length])
    print('** before **')
    print(str(doc))
    doc = apply_actions(doc, actions)
    print('** after **')
    print(str(doc))
    print('** changes **')
    if args.forth:
        for (typ, k, s) in actions:
            if typ:
                print(f's" {s}" {k} change')
            else:
                assert s == ''
                print(f'{k} moveto')
    else:
        print(json.dumps(actions, indent=4))
