# 6502 port notes

Speculative design notes for porting the Python prototype to a 6502
target (Forth or native assembly). Captured here so they don't clutter
the main README; expect them to drift as the actual port progresses
under `forth/`.

## Storage layout

The Python prototype keeps `Piece` and `Edit` instances on the heap
and links them with object references. On a 6502 we want everything
to live in a compact append-only "stack," with byte-sized fields and
nearby links so that we can use short (1-byte) offsets where possible.

```
[ start ]                         ; sentinel
[ end ]                           ; sentinel
[ source ] -> external source data
< edit 1 >                        ; pre/ins/post all optional
    [ pre  ]   --> shadowed data
    [ post ]   --> shadowed data
    [ ins  ]   --v  owned data
        "abc"
< edit 2 >
    [ pre  ]
    [ post ]
< edit 3 >                        ; <= stack pointer (currently undone)
    [ pre  ]
    [ ins  ]   --v
        "de"
                                  ; <= stack high-watermark
```

Indentation shows ownership: each `Edit` owns its `pre`/`ins`/`post`
pieces and (for `ins`) the inserted bytes.

### Piece (sketch)

- `[2]` prev -> Piece?              ; doubly linked list pointer
- `[2]` next -> Piece?
- `[0/2]` data -> owned or shadowed text
  (Python uses a `(source, start)` model since pointers are awkward;
  on the 6502 this is an absolute or stack-relative pointer.)
- `[1/2]` length -> length of the fragment
- (optional) inline storage for owned data

A flag bit (or `data == 0`) distinguishes primary pieces with inline
storage from secondary pieces that shadow.

### Edit (sketch)

- flags `[1]`: pre? post? ins? + 1/2 size for each + applied?
- `[1/2]` before -> Piece            ; chain insertion point (immutable)
- `[1/2]` after  -> Piece
- `[1/2]` unlinked_first, `[1/2]` unlinked_last
- `pre [8]`, `post [8]`, `ins [6+]`  ; 1-3 inline pieces; pre/post
  shadow data, ins includes inline storage if present.

## Locality observations

These motivate the variable-width pointer scheme above:

- Pieces in a single `Edit` are nearly contiguous in memory.
- A piece is usually close to the data it shadows.
- Shadowed data always sits *below* the shadowing piece on the stack
  (treating the source as the bottom).
- `ins` data tends to be small.
- Primary-piece links are 1–2 bytes or contiguous-ish, so most links
  fit in 1 byte.
- Primary pieces cap data at 256 bytes — modest limit on coalescing.

## Variable-width links

- Variable-size links inside a `Piece` are awkward to mutate (no
  spare room to grow short→long).
- Inside an `Edit` they're fine: `before`/`after` are immutable, and
  the unlinked-fragment links are guaranteed to land near the new
  pieces (since the owned fragment is also near).

## Buffers

The Python prototype lumps source and append text into the same set
of `PrimaryPiece`s. On the 6502 the natural split is two regions:

- source buffer (invariant once loaded)
- add buffer (append-only)

The piece list always starts with sentinel first/last, themselves
empty pieces with `null` next/prev respectively.

## Per-piece bookkeeping (open question)

Tracking line breaks inside each piece would let us answer "which
line is point on?" without a scan, but the Python perftest suggests
the BoL ladder dominates. Leaving line counts off for now.

```
each piece:
    prev
    next
    bufp
    #characters
    #line breaks      ; possibly
```

## Operations

- `goto point/line`  -> scan forward
- `goto rel`         -> scan forward/backward from current piece
- `insert`           -> append chars to add buffer; replace or modify
                        existing piece
- `delete`           -> replace or modify existing piece
- `*modify`          -> only allowed if piece is top-of-stack
                        (continuing a previous insert/delete)

Each insert or delete modifies one existing `piece->next` and one
`piece->prev`, and pushes one or more pieces (or extends TOS).

For undo of a `delete` we just need to remember the original size of
the TOS piece.

## Profiling the Python prototype

```sh
python3 -m cProfile -o ptedit.prof -m ptedit -P some_file
# Terminated after 1e+00s, 132 repaints

snakeviz ptedit.prof
```
