\ an edit tracks changes to the piece chain
\ with changes represented as:
\
\   before [pre] [ins] [post] after

\ 0: flags [ E----210 ]
\ 1/3: prev, next
\ 5/7: excl-first, excl-last
\ 9: [ pre ]		    flag 0
\ 17: [ post ]			flag 1 
\ 25: [ ins ] + data    flag 2

: edit-before ( edit -- piece )
  dup c@ %10000000 and if  7 + @  else  5 + @ piece<  then
;

: edit-after ( edit -- piece )
  dup c@ %10000000 and if  5 + @  else  7 + @ piece>  then
;

: edit] ( edit -- loc )
  0 swap dup edit-after swap 
  ( 0 piece edit )
  dup c@ %10 and if  \ post?
    c@ %1 and 3 lshift 9 + + piece# loc+
  else
    drop
  then 
;

: >pieces ( edit -- pre ins post )  	\ with zeros when absent
  dup 9 + swap c@
  ( edit' flags )
  dup %1 and if over 8 + swap else 0 -rot then
  ( pre|0 edit' flags )
  dup %10 and if over 8 + swap else 0 -rot then
  ( pre|0 post|0 edit' flags )
  %100 and 0= if drop 0 then
  ( pre|0 post|0 ins|0 )
  swap
;

: redo ( edit -- )
  \ link before - pre - ins - post - after
  dup edit-before
  over edit-after >r
  swap >pieces r> 
  ( before pre ins post after )
  \ set point to <0, post|after>
  over if over else dup then 0 swap point!
  \ link up the chain
  4 0 do ?pieces>< loop
  drop    
;

: undo ( edit -- )
  \ link before - x0 and x1 - after
  dup edit-before over 5 + @ pieces><
  dup 7 + @ swap edit-after pieces>< 
;

: :edit ( <ins> n -- edit ) \ <ins> is ( addr u | ch -1 | 0 )
  \ create a new edit:
  \ - split doc at point
  \ - remove n characters (left if n<0, right if >0)
  \ - insert ch (u=-1), string (u>0) or nothing (u=0)
  \ - connect to doc chain and set point

  here 0 c, 0 , 0 , swap \ allocate flags, prev, next
  ( <ins> edit n )

  >r point@ 2dup r@
  ( ... pt pt n  R: n )
  if \ delete n chars
    r@ loc+
    ( ... pt pt+del )
    r@ 0> if 2swap then
    ( ... pt pt+del | pt+del pt )  \ i.e. ( right left ) 
  then
  r> drop 
  ( ... ir rpiece il lpiece )
  dup ,     \ excl-first
  2over swap 0= if piece< then dup ,  \ excl-last
  ( ... ir rpiece il lpiece excl-last )
  piece> over = if %10000000 else 0 then -rot

  \ create pre? 
  ( ... ir rpiece flags il lpiece )
  over if 	\ il > 0 ?
    piece>| drop %1 or		\ set 'pre' flag    
  else
    2drop
  then
  -rot

  \ create post?
  ( ... flags ir rpiece )
  over if 	\ ir > 0 ?
    piece|< drop %10 or		\ set 'post' flag
  else
    2drop
  then

  \ create ins?
  ( <ins> edit flags )    \ <ins> is ( addr u | ch -1 | 0 )
  rot ?dup if
    -rot %100 or 2swap    \ set 'ins' flag
    ( edit flags <ins> )  \ <ins> is ( addr u | ch -1 )
    
    dup -1 = if 
      ( edit flags ch -1 )
      drop :piece^
    else 
      ( edit flags addr u )
      :piece$$			\ copy the source string
    then
    drop
  then
  ( edit flags )
  over c!				\ store flags
  ( edit )
  dup redo
  ( edit )
;

: change ( <ins> n edit -- edit' )
  \ modify edit if compatible or create a new one
  dup edit] point@ loc= if 
     
;

: test-edit 
  ." test-edit" .s cr
  doc doc-start point!
  doc doc. cr
  \ s" re" 3 :edit
  [char] Z -1 3 :edit
  doc doc. cr
  doc doc-start 3 loc+ point!
  s" ee" -1 :edit
  doc doc. cr
  .s
;

test-edit

\ edit/ \ delete forward char
\ edit\ \ delete backward char
\ edit^ \ insert char