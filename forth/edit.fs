: :edit ( addr u n | ch -1 true n | 0 n -- edit )
  ; create or modify current edit
  ; first split doc at point and remove n characters 
  ; (rightward if n is positive, leftward if n is negative)
  ; then insert a character (u = -1), string (u > 0) or nothing (u = 0)
;