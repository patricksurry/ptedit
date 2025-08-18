`ptedit` implements a miminal ascii text editor 
using the [piece-table data structure][piecetable].
The implementation is inspired by [Brown's post on *Piece Chains*][piecechain] and 
[Finseth's *Craft of Text Editing*][craft].
It's intended as a proof of concept for a lower-level implementation
for 6502 hardware in [Forth][tali] or native assembly

[piecetable]: https://en.wikipedia.org/wiki/Piece_table
[piecechain]: https://www.catch22.net/tuts/neatpad/piece-chains/
[craft]: https://www.finseth.com/craft/
[tali]: https://github.com/SamCoVT/TaliForth2

The piece table is an elegant way of representing an evolving document 
as a stack of immutable* edits to a source text.
This provides for efficient storage; offers native undo/redo;
is simple to reason about;
and seems particularly well suited for a system with primitive memory management.

The current state of an edited document comprises a doubly linked `Piece` list.
Each `Piece` represents a contiguous and immutable* fragment of text from the document.
Some `Piece`s provide their own data---such as when new text is inserted---and
others point to data owned by another `Piece`.  An *ur* `Piece` points
to the original source text, with sentinel `Piece`s marking the start and
end of the document.

Each change to the document is represented as an `Edit`, 
which stores a (completely reversible) change to the linked list.
Essentially the `Edit` tells how to swap a fragment of the original linked
list for a new fragment, composed of up to three new `Piece`s (`pre`, `ins` and `post`)
that it owns.
We can undo an `Edit` by simply re-swapping the old and new fragments into the 
document list, restoring the prior state.
Neither original nor new `Piece`s are modified, 
other than swapping the fragment in or out of the linked list.
In particular the underlying data is never changed*.
Multiple `Edit`s form a simple stack which we can undo by moving down the stack.
By tracking a stack pointer and high watermark---and not removing undone `Edit`s---we 
can redo re-applying `Edit`s higher on the stack and advancing the stack pointer.
If a new `Edit` is created after others have been undone, it simply replaces
the top of stack and resets the high watermark to automatically invalidate any later `Edit`s.

(*) Although it's perfectly feasible to make the `Edit` stack completely immutable
(other than swapping linked-list fragments when applying or undoing an `Edit`)
in practice we use a small optimization.   We allow the top-most `Edit` on the 
stack to coalesce with any compatible `Edit` that directly follows.  
For example, inserting the character "a" followed by "b" and then "c"
is collapsed to a single `Edit` that inserts "abc" rather than three independent ones. 
This provides for a much more compact document representation when driven 
by a typical editor controller supporting single key operations
like `insert-character`, `replace-character`, `delete-[forward|backward]-character`.
You can see this in action via the status bar in the prototype: 
the edit stack typically grows much more slowly than the number of keystrokes
you enter. 


Stack:

(indentation shows ownership)

[ start ]
[ end ]
[ source ] -> external source data
< edit 1 >          ; all three Piece are optional
    [ pre ] --> shadowed data
    [ post ] --> shadowed data
    [ ins ] --v  owned data
        "abc"
< edit 2 >
    [ pre ]
    [ post ]
< edit 3 >          ; <= stack pointer (edit 3 is currently undone)
    [ pre ]
    [ ins ] --v
        "de"
                    ; <= stack highwatermark 


Piece
---
- [2] prev -> Piece?    ; the linked list
- [2] next -> Piece?
- [0/2] data -> pointer to owned or shadowed text 
    [use source/start model in python since pointers are hard]
- [1/2] length -> length of the text fragment
- (optional) inline storage for owned data
[needs one bit flag for primary vs not, or use data MSB=0 to mean just length]

Edit
--- 
- flags[1]: pre? post? ins? 1/2 x 4, applied?
- [1/2] before -> Piece   ; the pieces where we swap the fragment in and out
- [1/2] after -> Piece    ; these are immutable
- old_start, old_end [1/2], [1/2]
- pre [8], post[8], ins[6+] ; 1-3 inline pieces, with pre/post shadowing data, and ins having inline storage (if present)


Observations:
- Pieces are often close together on the stack
- they often occur close to the data they shadow
- Pieces in an Edit are nearly contiguous
- data shadowed by a piece is always found below it on the stack 
  (if we pretend source data is at the bottom of the stack)
- Pieces that own new data (`ins`) is usually small

- Piece link: 1-2 bytes, or contiguous(-ish)
- Primary pieces limit data length to 256 bytes (so small limit on coalesce)

- variable size piece links in Piece are hard to swap (no space to make short->long)
- but in Edit they're OK since before/after immutable and links are ok 
  if old fragment is near (since owned fragment is def near)

Profile:

    python3 -m cProfile -o ptedit.prof -m src.ptedit -P foo
    > Terminated after 1e+00s, 132 repaints

    snakeviz ptedit.prof




source buffer (invariant)
add buffer (append only)

piece list / stack - always starts with sentinel first/last which are empty pieces with null next/prev respectively

each piece:
    prev
    next
    bufp
    #characters
    #line breaks

goto point / line => scan forward
goto rel => scan forward/backward from curr piece

insert - append chars to append buffer, replace or modify* piece
delete - replace or modify* piece
*modify - only allow if piece top of stack (continuing previous insert/delete)

each insert or delete modifies one existing piece->next and one piece->prev and
adds one or more pieces to stack (or continues mod on TOS)
for delete need original length of piece for undelete

undoable edit just needs to remember the modified next/prev, and original size of TOS piece for undelete
