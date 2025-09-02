        .cpu "65c02"
        .enc "none"

point = $f0		; ilo ihi piecel pieceh
ptadr = $f4		; piece>addr + ihi
pty = $f6      	; current Y value
ptpg = $f7		; pages left

; point is a loc with memory layout [ i piece ]

; addr u  where u is ulo/uhi  
; addr[0:u] equiv (addr-d)[d:u+d]
; take d = 256-ulo if ulo != 0 else 0
; then u+d = uhi*256 + ulo + 256-ulo = <uhi+1,0>

point_next_piece:
		ldy #5
		lda (point+2),y		; MSB
		beq +				; doc end
		pha
		dey
		lda (point+2),y		; LSB
		sta point+2
		pla
		sta point+3			; non-zero
		stz point+0
		stz point+1
+
		rts


point_iter:
	; set up point tmps for forward iteration
		ldy #3
		lda (point+2),y		; copy piece.addr
		sta ptadr+1
		dey
		lda (point+2),y
		sta ptadr
		dey
		lda (point+2),y		; uhi is number of pages
		sta ptpg
		dey
		lda (point+2),y		; ulo
		and #$ff
		inc a				; 256 - ulo
		sta pty
        beq +				; if 256 - ulo !=0 ...
		inc ptpg			; one more page
		sec
		lda ptadr			; adjust addr lower
		sbc pty
		sta ptadr
		bcs +
		dec ptadr+1
+		
		rts
		 

point_at_next:
; return char at point in A, increment
		ldy pty
		bne +
		lda ptpg			; finished piece
		bne +
		jsr point_next_piece
		beq _end			; A=0 if end
		jsr point_iter
+
		lda (ptadr),y		; fetch char
		inc pty				; move point (TODO actual point)
		bne _end
		dec ptpg
_end
		rts   
