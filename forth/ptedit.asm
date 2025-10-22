        .cpu "65c02"
        .enc "none"

; point is a Location, stored as a double word
; with a reference to a piece and offset within it
;
;   0       2
;  +--------+--------+
;  | piece  | offset |
;  +--------+--------+

point_t .struct
piece	.word ?
offset 	.word ?					; piecel pieceh  offsetlo offsethi  (4 bytes)
		.endstruct

; where piece contains a counted string and next/prev pointers
;
;   0      2      4      6
;  +------+------+------+------+
;  |  u   | addr | next | prev |
;  +------+------+------+------+

s16_t 	.struct
n		.word \1
s		.word \2
		.endstruct

piece_t .struct
data    .dstruct s16_t, \1, \2
next	.word \3
prev	.word \4
		.endstruct


	* = $f0

point:	.dstruct point_t
iter:	.dstruct s16_t			; remaining data in current piece.  MSB=0 signals end of doc

line_buf:	.word ?
wrap_point:	.dstruct point_t
wrap_col:	.byte ?
wrap_flag: 	.byte ?


COL_MAX = 40
TAB_MASK = %11

	* = $4000

point_iter_start:
	; set up for iteration with iter.s pointing to the current character
	; and iter.n counting the number of characters remaining in the piece
	; set iter ( u' addr' ) to current piece data ( u-offset addr+offset )
		ldy #0
		lda (point.piece),y		; LSB of u
		sec						; u' = u - offset
		sbc point.offset
		sta iter.n
		iny
		lda (point.piece),y
		sbc point.offset+1
		sta iter.n+1

		clc						; addr' = addr + offset
		iny
		lda (point.piece),y		; LSB of addr
		adc point.offset
		sta iter.s
		iny
		lda (point.piece),y
		adc point.offset+1
		sta iter.s+1

		rts


point_iter_next:
	; after calling point_iter_start to set up iteration, use point_iter_next to advance point
	; leaving iter.s pointing to the current character
	; preserves Y

		lda iter.n				; decrement remaining chars, u'--
		bne +					; need borrow?
		lda iter.n+1
		beq _done				; if u' is 0 already just stay at EoD
		dec iter.n+1
+
		dec iter.n
		bne +
		lda iter.n+1			; is this piece finished?
		beq point_next_piece
+
		inc iter.s				; addr'++
		bne +
		inc iter.s+1
+
		inc point.offset		; keep point offset in sync
		bne +
		inc point.offset+1
+
_done:
		rts


point_next_piece:
	; set point to [ piece->next 0 ]
		phy
		ldy #piece_t.next+1
		lda (point.piece),y		; MSB of piece->next (0 if done)
		pha						; stash while we fetch LSB
		dey
		lda (point.piece),y		; LSB of piece->next
		sta point.piece			; update point->piece
		pla
		sta point.piece+1
		stz point.offset		; set offset to zero
		stz point.offset+1

		; copy point's piece data [ u addr ] to iter
		ldy #piece_t.data+3
-
		lda (point.piece),y
		sta iter,y
		dey
		bpl -

		ora iter.n+1			; A has LSB of iter.n: if MSB also zero, we're at EoD
		bne +

		; otherwise point iter.s at iter.n == 0 to generate char zero at EoD
		lda #iter.n
		sta iter.s				; MSB already zero
+
		ply
		rts



format_line:
	; format characters from point into line_buf
	; handling wrapping and special characters

		jsr point_iter_start
		ldy #0
		stz wrap_col			; track the latest soft break
_loop:
		stz wrap_flag
		lda (iter.s)

		cmp #' '
		bcc _lo
		beq _sp					; C=1 for space
		cmp #$7F
		bcs _esc3				; C=0 for non-space
_sp:
		rol wrap_flag			; set bit 0 to 1 for space
_out:
		sta (line_buf),y
		iny
_inc:
		jsr point_iter_next		; consumed current character (preserve Y)

		lda wrap_flag			; $ff for hard wrap, $1 for soft wrap
		beq _cont
_wrap:
		sty wrap_col			; update wrap column
		bmi _epilog

		; for soft wrap save point so we can revert
		ldy #3
-
		lda point,y
		sta wrap_point,y
		dey
		bpl -

		ldy wrap_col			; recover Y and carry on

_cont:
		cpy #COL_MAX
		bcc _loop

_epilog:
		; if 0 < wrap_col < y retreat point and column

		lda wrap_col
		beq _fill

		cpy wrap_col
		beq _fill

		ldy #3
-
		lda wrap_point,y		; retreat point
		sta point,y
		dey
		bpl -

		ldy wrap_col			; retreat column

_fill:							; fill buffer with zero
		lda #0
		bra +
-
		sta (line_buf),y
		iny
+
		cpy #COL_MAX
		bne -

		rts

; special cases

_tab:
		inc wrap_flag
-
		sta (line_buf),y
		iny
		tya
		and #TAB_MASK
		beq _inc
		lda #0
		bra -

_zero:
		lda iter.s+1			; end of doc?
		bne _esc2				; escape if not
		; fall through to newline
_nl:
		dec wrap_flag			; set to $ff
		bra _out

_lo:
		cmp #0					; \0 could mean end of doc
		beq _zero
		cmp #10					; \n
		beq _nl
		cmp #9					; \t
		beq _tab
		; fall through to escape

_esc2:
		; display lo char escapes as ^C
		cpy #COL_MAX - 1
		bcs _epilog
		lda #'^'
		sta (line_buf),y
		iny
		lda (iter.s)
		ora #$40
_out2:
		bra _out

_esc3:
		; display hi char escapes as \DD
		cpy #COL_MAX - 2
		bcs _epilog
		lda #'\'
		sta (line_buf),y
		iny
		lda (iter.s)
	; emit A as two hex digits, preserving Y
		pha

		lsr
		lsr
		lsr
		lsr

		phy
		tay
		lda hex_digits,y
		ply
		sta (line_buf),y
		iny

		pla
		and #$F

		phy
		tay
		lda hex_digits,y
		ply

		bra _out2



hex_digits:
		.text "0123456789ABCDEF"


	* = $4400

test:
		lda doc_start.next		; set point to start.next
		sta point.piece
		lda doc_start.next+1
		sta point.piece+1
		lda #2
		sta point.offset		; start at offset 2
		stz point.offset+1

		stz line_buf				; write to $400
		lda #4
		sta line_buf+1

test_format:
-
		jsr format_line
		lda iter.s+1
		beq +
		lda line_buf
		and #$c0
		clc
		adc #$40
		sta line_buf
		bcc -
		inc line_buf+1
		bra -
+
		brk

test_iter:
		jsr point_iter_start
		ldy #0
_loop:
		lda (iter.s)
		sta (line_buf),y
		iny
		cpy #20
		beq _done
		phy
		jsr point_iter_next
		ply
		bra _loop
_done:
		brk


doc_start:	.dstruct piece_t, 0, 0, doc_p1, 0		; piece: [len, addr, next, prev]
doc_end:	.dstruct piece_t, 0, 0, 0, doc_p2
doc_p1:		.dstruct piece_t, doc_n1, doc_s1, doc_p2, doc_start
doc_s1:		.text "a banana", $be, 6, ", a tab", 9, "and", 9, "another", 10, 9, "And its"
doc_n1 = * - doc_s1
doc_p2:		.dstruct piece_t, doc_n2, doc_s2, doc_end, doc_p1
doc_s2:		.text " peel. the quick brown fox jumps over the lazy dog"
doc_n2 = * - doc_s2
