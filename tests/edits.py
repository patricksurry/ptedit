import random
from collections import namedtuple


source = open('alice1.asc').read()[:100]


class Edit:
    def apply(self, s: str) -> str:
        ...

    @property
    def delta(self) -> int:
        ...

    @classmethod
    def random(kls, n: int) -> 'Edit':
        ...


class Insert(Edit):
    def __init__(self, offset: int, s: str):
        self.offset = offset
        self.s = s

    @property
    def delta(self):
        return len(self.s)

    @classmethod
    def random(kls, n: int) -> 'Insert':
        offset = random.randint(0,n)
        length = 1 + random.binomialvariate(100, 0.1)
        k = random.randint(0, len(source)-length)
        s = source[k:k+length]
        return Insert(offset, s)

    def apply(self, s: str) -> str:
        return s[:self.offset] + self.s + s[self.offset:]

    def __repr__(self):
        return f"insert @ {self.offset}: '{self.s}'"


class Delete(Edit):
    def __init__(self, offset: int, length: int):
        self.offset = offset
        self.length = length

    @property
    def delta(self) -> int:
        return -self.length

    @classmethod
    def random(kls, n: int) -> 'Delete':
        offset = random.randint(0,n)
        length = 1 + random.binomialvariate(100, 0.1)
        return Delete(offset, min(length, n-offset))

    def apply(self, s: str) -> str:
        return s[:self.offset] + s[self.offset+self.length:]

    def __repr__(self):
        return f"delete @ {self.offset}+{self.length}"


def randedit(n: int) -> Edit:
    return Insert.random(n) if random.random() < 0.5 else Delete.random(n)


def randedits(n: int, k: int) -> list[Edit]:
    edits: list[Edit] = []
    for _ in range(k):
        e = randedit(n)
        edits.append(e)
        n += e.delta
    return n, edits


s = source[:]
random.seed(42)
n, edits = randedits(len(s), 32)
print(edits)
print(f"Starting length {len(s)}, expecting {n} after edits")
for e in edits:
    print(len(s))
    s = e.apply(s)
print(len(s))
assert len(s) == n
print(s)

