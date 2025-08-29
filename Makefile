TALI = ../6502/tali
C65 = $(TALI)/tools/c65/c65
FPP = ../6502/advent-forth/scripts/fpp.py

src.fs: forth/*.fs
	cat forth/piece.fs forth/doc.fs forth/render.fs > /tmp/src.fs
	python3 $(FPP) -o src.fs /tmp/src.fs

run: src.fs
	( \
		dd if=src.fs bs=4K conv=sync ; \
		dd if=tests/alice1flow.asc bs=2K conv=sync ; \
		dd if=../6502/tali/taliforth-c65.bin \
	) > image.bin
	$(C65) -r image.bin


# : test_move $f006 c@ $5000 $3000 1920 cmove $f007 c@ $f008 2@ ud. ;  ok
# test_move 31784  ok (31fps; 16 cycles/char moved)
# : test_type $f006 c@ $5000 1920 type $f007 c@ $f008 2@ ud. ;  ok
# test_type ... 73221 (13 frames/sec)