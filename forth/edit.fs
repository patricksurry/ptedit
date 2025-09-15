\ an edit tracks changes to the piece chain
\ with changes represented as:
\
\   before [pre] [ins] [post] after

\ flags
\ prev, next
\ before, after
\ before>, after<
\ [ pre ]			0 or 1
\ [ post ]			0, 1, 2 
\ [ ins ] + data    0, 1, 2, 3

: :edit ( <ins> n -- edit ) \ <ins> is ( addr u | ch -1 | 0 )
  \ create a new edit:
  \ - split doc at point
  \ - remove n characters (left if n<0, right if >0)
  \ - insert ch (u=-1), string (u>0) or nothing (u=0)

  here 0 c, 0 , 0 , swap \ allocate flags, prev, next
  ( <ins> edit n )

  ?dup if \ delete n chars
    >r point@ 2dup r@ loc+ ( pt pt+del )
    r> if 2swap then ( right left ) aka ( ir rpiece il lpiece )
  then
  dup piece< \ todo => before
  over if piece>| drop %1 else 2drop 0 then
  \ todo => flags
  2dup swap if piece> then \ todo => after
  over if piece|< drop %10 else 2drop 0 then
  \ todo => flags

  else \ no delete
    point@ over if \ split piece at point
      ( <ins> edit u piece )
      \ before, after  = piece<, piece>
      \ before> after< = piece, piece
      dup piece< , dup piece> ,
      dup , dup ,
      piece| 2drop \ allocate new pieces, drop pointers
      %11 over c,  \ both pre and post are present
    else \ point offset is 0
      ( <ins> edit u piece )
      \ before,  after  = piece<, piece
      \ before>, after< = piece, piece<
      dup piece< 2dup , , swap , , 
      drop
      0 over c,    \ both pre and post are empty
    then
    ( <ins> edit )
    swap  
  then
;


\ edit/ \ delete forward char
\ edit\ \ delete backward char
\ edit^ \ insert char