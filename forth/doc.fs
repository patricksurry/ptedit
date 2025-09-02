
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
;

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

' test_alice cycles cr
.( cycles: ) ud. cr

\ was 1F5A10 (2.05M) with loc1+  16BC3D (1.5M)