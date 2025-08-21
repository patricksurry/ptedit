refactor as:
- operator with mode enum selecting keymap (not flags)
- editor (controller) for managing the doc
- formatter for managing output

- [ ] isearch remember last; do we need direction state if separate key?

- [ ] case-sensitivity for search (lc match either, UC match only)

- [ ] with incomplete last line backward-line doesn't work (presumably because preferred col is non-zero; should override if already at BOL?)

- [ ] end of doc stick at end of screen (or guard), not preferred row after M-E

- [ ] del word, line -> clipboard

- [ ] goto line?

- [ ] toggle line numbers?

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
