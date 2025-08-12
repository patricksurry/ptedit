https://www.catch22.net/tuts/neatpad/piece-chains/
https://en.wikipedia.org/wiki/Piece_table

https://www.finseth.com/craft/

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
