- the naive BOL routines are ridicously inefficient
    - how to measure it?
    - improve with a recent BOL cache, last index?

- if mark is not None, then highlight characters between mark&point (or vice versa)

- dirty flag should be based on last save, not edit stack

- incomplete last line behaves oddly

- del word, line

- cut/copy/paste

- [x] incremental search
    - RET (or non-search-mode action) moves point just past the end of the next occurrence of those characters
    - if search string is modified (add or remove character)
    - the search restarts from the original point
    - the repeat search finds subsequent matches.  
    - repeat search without entering a new search string reuses the old one (if there is one)

- goto line?

- toggle line numbers?
