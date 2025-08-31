core:

- should delete be in terms of location not offset? (special case for +/-1)

- could we just track direction of mark from point easily so don't need to check?  (what about search?)


rendering:

- with mutation in perf test, frame rate drops from 90 to 30

- next_glyph should keep a lookahead buffer rather than scanning back and forth.
  be careful at start of line not to buffer everything.  
  
- add a test with > #cols non-breakable chars.

- do we need the screen.clear() if we add padding at end of doc?

- don't return '', width 0, instead ch=0, width=0 ?


keyboard:

- [ ] del or ctrl v should del marked region if any; other printables?
      cf: emacs transient mark mode

- [ ] isearch show search in status

- [ ] isearch remember last; do we need direction state if separate key?

- [ ] isearch_direction and trigger seem a bit of a mess


bugs:

- [ ] ? after Meta-E, the end of doc is at preferred row so half screen is wasted, rather than showing more preceding lines.


features:

- [ ] wrap/non-wrap mode  (guard_cols, preferred left always 0)

- [ ] ? crlf handling

- [ ] ? goto line key

- [ ] ? toggle line numbers


done:

- [x] logging for number of chars scanned via back & forth during each paint

- [x] why did perftest get so slow?  __len__ and data properties??

- [x] autosave ~ after changes and exit incl ctrl-C

- [x] with incomplete last line backward-line doesn't work (presumably because preferred col is non-zero; should override if already at BOL?)

- [x] fix status bar; 

- [x] status show msg

- [x] refactor mark/point inverse (if mark; inverted = mark <= top, ...)

- [x] ctrl-L  clear preferred top (recenter screen) - controller->renderer

- [x] add char at point in hex in status, e.g. $0a

- [x] ed.squash should remember position

- [x] case-sensitivity for search (lc match either, UC match only)

- [x] cut/copy/paste -> clipboard

- [x] if mark is not None, then highlight characters between mark&point (or vice versa).  for isearch and copy/paste 

- [x] the naive BOL routines are ridicously inefficient

- [x] dirty flag should be based on last save, not edit stack

- [x] incremental search
    - RET (or non-search-mode action) moves point just past the end of the next occurrence of those characters
    - if search string is modified (add or remove character)
    - the search restarts from the original point
    - the repeat search finds subsequent matches.  
    - repeat search without entering a new search string reuses the old one (if there is one)



performance: (80x23+1 = 1840 char display)
- before cache, ~147 fps: 433650 x get_char ~ 2950/frame
- fwd cache, ~240 fps: 350217 x get_char ~ 1459/frame
- bkwd cache


from doc midpoint:  (actual 1446 char/frame)
- before cache: ~47 fps: 443856 get_char ~ 9444/frame
+ fwd cache: ~221 fps: 358662 x get_char ~ 1622/frame
+ bkwd: ~211 fps: 341967 ~ 1620/frame

"""
other keys to map

set mark C-' ' == C-@
del char/word forward/backward
cut line C-K
help
goto line number
select all, e.g. C-A
cut/copy/paste C-C/C-X/C-V
find C-F/C-G/C-R or P for back
bksp C-H

C-</|  0x1c
C-=]}  0x1d
C->^~  0x1e
C-?_DEL 0x1f
"""
