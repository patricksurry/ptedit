
: highlight s\" \e[7m" type ;         
: normal s\" \e[m" type ;

: test_highlight ." fee" highlight ." fie" normal ." foe" ;

test_highlight
