hex
here .

\ A piece is a string with a prev and next pointer
\ with an 8 byte memory footprint.   Note 2! and 2@
\ preserve memory order with the downward growing 
\ data stack, so ( addr u ) 2@ matches the first four bytes
\
\   0      2      4      6
\  +------+------+------+------+
\  |  u   | addr | next | prev |
\  +------+------+------+------+

: :piece ( addr u prev next -- piece )
  \ memory layout is [ u addr next prev ] so 2@ gives ( addr u )
  2swap , , , , here 8 -
;
: :piece0 ( -- piece )        \ empty
  0 0 0 0 :piece ;
: :piece^ ( c -- piece )      \ single character
  here 8 + 1 0 0 :piece swap c, ;
: :piece$ ( addr u -- piece )  \ external string
  0 0 :piece ;
: :piece$$ ( addr u -- piece ) \ copied string
  2dup :piece$ -rot here swap cmove ( piece )
  here over 2 + ! dup @ allot
;

: piece$ ( piece -- addr u )  2@ ;    \ get string from piece
: piece> ( piece -- piece' )  4 + @ ; \ next piece
: piece< ( piece -- piece' )  6 + @ ; \ prev piece
: piece# ( piece -- u )  @ ;          \ length of piece data
: pieces>< ( p q -- )  2dup 6 + ! swap 4 + ! ; \ link two pieces
: piece| ( piece u -- piece' piece'' ) 
  \ split a piece at u < piece#, preserving original prev/next
  over 4 + 2@ swap 2>r ( piece u  R: next prev )
  over 2 + @ over r> 0 :piece ( piece u piece' )
  -rot swap 2@ rot /string 0 r> :piece ( piece' piece'' ) 
;
: piece. ( piece -- )   \ show a piece
  [char] < emit space dup 6 + @ u. space 
  dup 4 + @ u. [char] > emit 4 spaces
  dup 2 + @ u. space 
  2@ type
;
: pieces. ( piece -- )  \ show a list of pieces 
  begin
    dup u. dup piece> swap piece. cr ?dup 0=
  until
;
 
\ loc is just a double word ( i piece )
\ so we don't use an explicit constructor (2@ and 2! are fine)

\ get char at loc, or 0 if piece is empty
: loc^ ( i piece -- c )  piece$ ( i addr u ) if + c@ else 2drop 0 then ;
\ move location by n
: loc1+ ( i piece -- i' piece' )
  dup piece# ?dup if
    ( i p n )
    rot 1+ tuck = if
      ( p i+1 )
      drop piece> 0
    then
    swap
  then 
;

: loc+ ( i piece delta -- i' piece' )
  ?dup if 
    rot +
    ( piece i' )
dup if 
  dup 0> if
    begin
      over piece# dup if   \ len(piece) > 0 ?
        2dup u< invert     \ i' >= len(piece) ?
        ( piece i' u f )
      else
        swap 0             
        ( piece 0 i' 0 )
      then
      while
      - swap piece> swap
      ( piece' i'' )
    repeat
    drop
    ( piece' i' )
  else
    begin
      swap piece< swap over piece# 
      ( piece< i' n )
      dup if
        + dup 0< 
        ( piece< i'+n f )
      else 
        nip 0 
        ( piece< 0 0 )
      then
      while
      ( piece' i'' )
    repeat
  then
then
  then
  swap
  ( i' piece' )
; 

cr here . cr

0 value doc

: test_split
  s" banana" 1234 5678 :piece
  dup piece. cr
  2 piece| .s cr
  piece. piece.
;

test_split
cr

: test_doc
  :piece0 s" bar" :piece$ s" foo" :piece$ :piece0
  dup to doc
  over pieces>< over pieces>< swap pieces><
  doc pieces.
  doc piece> 4 dump
;

test_doc
cr

: test_fwd
  ." forward: "
  0 doc piece>  \ starting loc
  begin
    2dup loc^ ?dup while
    emit loc1+
  repeat
  space ud.
;

test_fwd
cr

: test_bkwd
  ." backward: "
  0 doc piece> piece> piece>
  begin
    -1 loc+ 
    2dup loc^ ?dup while
    emit
  repeat
  space ud.
;

test_bkwd
cr
