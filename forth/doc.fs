$f0 constant point
: point@ ( -- loc ) point 2@ ;
: point! ( loc -- ) point 2! ;

: doc-start ( doc -- u piece ) piece> 0 swap ;
: doc-end ( doc -- u piece ) 8 +  0 swap ;

: :doc ( addr u -- doc )
  \ pieces in memory: start end [ body ]
  here -rot
  :piece0 -rot
  :piece0 -rot
  ( doc p0 p1 addr u )
  ?dup if
    :piece$ tuck swap pieces><
  else
    drop
  then
  pieces><
  dup doc-start point!
;

: doc. ( doc -- )
  doc-start
  begin 
    \ at point?
    2dup point@ rot = -rot = and if [char] ^ emit then
    \ at piece start?
	over 0= if [char] | emit then
    2dup loc^
    ?dup while
    emit loc1+
  repeat
  2drop
;

: test_doc.
  s" foobar" :doc dup doc. cr \ ^|foobar|
  point@ 3 loc+ point! dup doc. cr \ |foo^bar| 
  point@ 1000 loc+ point! doc. cr \ |foobar|^
;

.s cr
test_doc.

: test_alice
  $5000 $2d00 :doc
  cr ." doc: " .s cr
  dup $18 dump
  doc-start
  $780 0 do
    2dup loc^ emit
    loc1+
  loop
  cr ." loc: " ud. cr
;

: cycles ( xt -- ud )
  $f006 c@ drop execute $f007 c@ drop $f008 2@
;

\ ' test_alice cycles cr
\ .( cycles: ) ud. cr

\ was 1F5A10 (2.05M) with loc1+  16BC3D (1.5M)

.s cr