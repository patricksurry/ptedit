# ptedit

A minimalist ASCII text editor built around the [piece-table data structure][piecetable]. 
The Python reference implementation explores basic editor wiring using the piece-table concept. 
The eventual aim is a 6502 [Forth][tali]/assembly port.
The code is inspired by Brown's [*Piece Chains*][piecechain] and Finseth's
[*Craft of Text Editing*][craft].

[piecetable]: https://en.wikipedia.org/wiki/Piece_table
[piecechain]: https://www.catch22.net/tuts/neatpad/piece-chains/
[craft]: https://www.finseth.com/craft/
[tali]: https://github.com/SamCoVT/TaliForth2

## Quick start

```sh
uv sync
uv run python -m ptedit path/to/file.txt
```

Key bindings live in `src/ptedit/controller.py`. They follow loose
Emacs conventions: arrows move, `C-S`/`C-R` start incremental search,
`Esc` enters meta mode (`Esc s` saves, `Esc q` quits, `Esc m` sets
mark, `Esc c`/`x`/`v` are copy/cut/paste, etc.).

## Why a piece table?

A piece table represents an evolving document as an immutable source
plus a chain of *pieces*, each pointing at a span of either the
original source or an append-only buffer of inserted text. Edits never
rewrite text in place; they just rewire the chain. That gives:

- compact storage even after heavy editing,
- native undo/redo (each edit knows the chain fragment it replaced),
- simple reasoning — pieces are immutable once linked,
- a good fit for systems with primitive memory management (no
  realloc/compaction in the hot path).

## Data model

The document is a doubly-linked list of `Piece`s, bracketed by two
empty sentinel pieces. Each `Piece` represents a contiguous, immutable
span of text. A `PrimaryPiece` owns its data; a `SecondaryPiece`
points into the data of some primary piece. The *ur*-piece loaded
from disk is a primary piece spanning the whole source file:

```
[start] <-> [ "the quick brown fox" ] <-> [end]
                     ^
                     |
                the ur piece 
```

Every change is captured as an `Edit` that swaps a fragment of the
chain for a new one of up to three pieces — `pre`, `ins`, `post`:

```
      [before] <-> [ "some text" ] <-> [after]

Edit:           -> [ "some text" ] <-
                     (unlinked)

      [before] <-> [ "some " ] <-> [ "new " ] <-> [ "text" ] <-> [after]
                       pre             ins           post
                  (shadows left)   (new data)    (shadows right)
```

The `Edit` keeps pointers to the unlinked fragment
(`exclude_first`/`exclude_last`), so undo can simply swap it back in.
`Edit`s also form doubly-linked list; the current document state
is "everything up to and including the active `Edit`," redo walks
forward, and a new edit after some undos truncates the forward chain.

As an optimization the most recent `Edit` may be extended in place
when the next change is contiguous and compatible (e.g. typing
`a`, `b`, `c` collapses into a single insert of `"abc"`). You can
watch this in the status bar — `eds N/M` typically grows more
slowly than your keystroke count.

See `src/ptedit/piece.py` and `src/ptedit/edit.py` for more, including
an ASCII diagram of an `Edit`'s before/after links.

## MVC architecture

```
      +--------------------------------------------+
      |                Controller                  |
      | (curses IO, keymap, status bar, save/quit) |  
      +--------+--------------------------+--------+
               |                          |                        
               v                          v
      +-----------------+        +-----------------+       
      |      Editor     |        |     Display     |
      |    (commands)   |        |(paint, find_top)|
      +-----------------+        +--------+--------+       
               |                          |
               |                          v
               |        +--------------------------+
               +------> |          Layout          |
               |        | (ladder, line mvmt, fmt) |
               |        +--------------------------+
               |                          |
               v                          v
      +--------------------------------------------+
      |                 Document                   |
      | (Piece chain, Edits, point, find/ins/del)  |
      +--------------------------------------------+
```

| Layer | Files | Role  |
|-------|-------|-------|
| Model | `piece.py`, `edit.py`, `location.py`, `document.py` | The piece-table itself: pieces, edits, point locations, and a `Document` API for char/region access. |
| Layout | `layout.py` | Maps the document onto a screen grid: caches beginning-of-line marks, formats one line of glyphs, exposes line/page navigation. |
| View | `display.py`, `screen.py` | Walks lines from `Layout` and paints them via the abstract `Screen`, tracking sticky-top scroll state; `paint` reads the document (point saved/restored) and never mutates model or movement state. |
| Controller  | `editor.py`, `controller.py` | `Editor` owns mark/clipboard/isearch state and exposes named commands; `Controller` binds keys and renders the status bar. |

The split keeps each concern testable in isolation: the model has no
idea a screen exists, `Layout` knows columns and rows but not curses,
`Display` paints into a `Screen` that is mocked in tests, and the
`Editor` talks to `Display` only through a `notify` callback.

Five invariants pin the layering (see `docs/rendering.md` for the
rendering side):

1. **Commands complete themselves.** After a key's action runs, the
   point is final — vertical moves land on their goal column at
   command time; nothing is deferred to the next paint.
2. **`paint` is read-only.** It saves the point on entry, restores it
   before returning, and never mutates model or movement state.
3. **`Layout` is the ladder's only writer.** `Display` consumes the
   BoL cache through accessors and never appends or truncates it.
4. **Screen damage is one number** — the lowest document position
   whose on-screen bytes may be stale; paint turns it into a single
   first-dirty row.
5. **One change hook.** `Document.on_change` is consumed by `Display`
   alone: forward edits remap caches incrementally (the typing hot
   path); undo, redo, and squash reset them wholesale.

## Repository layout

```
src/ptedit/      editor source (see table above)
tests/           pytest suite + sample documents
docs/plans/      design notes & perf baselines
docs/            6502 port notes (6502-port-notes.md)
forth/           in-progress 6502 Forth port (see Makefile)
```

## Development

```sh
uv run pytest                          # 54 tests
uv run python -m ptedit -P file        # default 'insert' perftest scenario
uv run python -m ptedit -P up_from_end file
```

Per-scenario performance baselines live in
`docs/plans/perf-baseline.md`. Notes intended for the eventual 6502
port (byte-level `Piece`/`Edit` layout, locality observations, etc.)
live in [`docs/6502-port-notes.md`](docs/6502-port-notes.md).
