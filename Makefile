TALI = ../6502/tali
C65 = $(TALI)/tools/c65/c65
FPP = ../6502/advent-forth/scripts/fpp.py

all: run

ptedit.fs: forth/*.fs
	cat forth/piece.fs forth/doc.fs forth/render.fs > /tmp/ptedit.fs
	python3 $(FPP) -o ptedit.fs /tmp/ptedit.fs

pteditasm.bin: forth/ptedit.asm
	64tass --nostart --output pteditasm.bin --vice-labels --labels=forth/pteditasm.sym forth/ptedit.asm

run: ptedit.bin
	$(C65) -r ptedit.bin

ptedit.bin: ptedit.fs pteditasm.bin
	( \
		dd if=ptedit.fs bs=3K conv=sync ; \
		dd if=pteditasm.bin bs=1K conv=sync ; \
		dd if=tests/alice1flow.asc bs=12K conv=sync ; \
		dd if=../6502/tali/taliforth-c65.bin \
	) > ptedit.bin

# $4000 $c00 evaluate
# $
# : test_move $f006 c@ $5000 $3000 1920 cmove $f007 c@ $f008 2@ ud. ;  ok
# test_move 31784  ok (31fps; 16 cycles/char moved)
# : test_type $f006 c@ $5000 1920 type $f007 c@ $f008 2@ ud. ;  ok
# test_type ... 73221 (13 frames/sec)