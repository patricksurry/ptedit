- [ ] if mark is not None, then highlight characters between mark&point (or vice versa).  for isearch and copy/paste

- [ ] incomplete last line behaves oddly

- [ ] del word, line

- [ ] cut/copy/paste

- [ ] goto line?

- [ ] toggle line numbers?

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