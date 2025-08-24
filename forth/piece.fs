\ A piece is a string with a prev and next pointer:
\ i.e. ( addr u prev next )

: :piece ( addr u prev next -- piece )
  \ memory layout is [ u addr next prev ] so 2@ gives (addr u)
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
  2@ type cr
;
: pieces. ( piece -- )  \ show a list of pieces
  cr begin
    dup u. dup piece> swap piece. ?dup 0=
  until
;
 
: :loc ( piece u -- loc )
  \ memory is [ piece u ] so 2@ gives ( u piece )
  swap , , here 4 -
;
\ get char at loc, or 0 if piece is empty
: loc^ ( loc -- c )  2@ piece$ ( i addr u ) if + c@ else 2drop 0 then ;
: loc+ ( loc n -- )
  ?dup 0= if drop exit then
  over 2@ -rot + 
  ( loc piece n' )
dup if 
  dup 0> if
    begin
      over piece# dup if   \ len(piece) > 0 ?
        2dup u< invert     \ n' >= len(piece) ?
      else
        swap 0             \ ( loc piece 0 n' 0 )
      then
      ( loc piece n' u f )  
      while
      - swap piece> swap
      ( loc piece' n'' )
    repeat
    drop
    ( loc piece u )
  else
    begin
      swap piece< swap over piece# 
      ( loc piece< n' u )
      dup if
        + dup 0< 
        ( loc piece< n'+u f )
      else 
        nip 0 
        ( loc piece< 0 0 )
      then
      while
    repeat
  then
then
  swap rot 2!
; 

.s

0 value doc
0 value point

: test_doc
  hex :piece0 s" bar" :piece$ s" foo" :piece$ :piece0
  dup to doc
  over pieces>< over pieces>< swap pieces><
  doc pieces.
  doc piece> 0 :loc to point
  point 4 dump
;

test_doc

: test_fwd
  ." forward:" cr
  begin
    point loc^ ?dup while
    emit point 1 loc+
  repeat
  point 4 dump
;

test_fwd

: test_bkwd
  ." backward:" cr
  begin
    point -1 loc+ 
    point loc^ ?dup while
    emit
  repeat
  point 4 dump
;

test_bkwd
