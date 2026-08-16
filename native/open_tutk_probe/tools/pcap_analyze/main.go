package main

import (
	"encoding/binary"
	"fmt"
	"io"
	"os"

	"github.com/AlexxIT/go2rtc/pkg/tutk"
)

func main() {
	f, err := os.Open(os.Args[1])
	if err != nil {
		panic(err)
	}
	defer f.Close()
	global := make([]byte, 24)
	if _, err = io.ReadFull(f, global); err != nil {
		panic(err)
	}
	var firstMicros uint64
	rdtOnly := len(os.Args) > 2 && os.Args[2] == "rdt"
	kind45Shown := 0
	for packet := 0; ; packet++ {
		header := make([]byte, 16)
		if _, err = io.ReadFull(f, header); err == io.EOF {
			return
		}
		if err != nil {
			panic(err)
		}
		micros := uint64(binary.LittleEndian.Uint32(header))*1_000_000 +
			uint64(binary.LittleEndian.Uint32(header[4:8]))
		if firstMicros == 0 {
			firstMicros = micros
		}
		length := binary.LittleEndian.Uint32(header[8:12])
		frame := make([]byte, length)
		if _, err = io.ReadFull(f, frame); err != nil {
			panic(err)
		}
		if len(frame) < 42 || frame[12] != 0x08 || frame[13] != 0x00 || frame[23] != 17 {
			continue
		}
		ip := frame[14:]
		udp := ip[int(ip[0]&0x0f)*4:]
		if len(udp) < 8 {
			continue
		}
		payload := udp[8:]
		decoded := tutk.ReverseTransCodePartial(nil, payload)
		if rdtOnly {
			if len(decoded) < 48 || decoded[14] != 3 || string(decoded[28:32]) != "\x5a\x97\xc2\xf1" {
				continue
			}
			kind := decoded[32]
			seq := binary.LittleEndian.Uint32(decoded[36:40])
			if kind == 0x02 || kind == 0x46 {
				if seq%250 != 0 {
					continue
				}
			}
			fmt.Printf("%03d +%.6fs %d->%d kind=%02x seq=%d size=%d flags=%x\n", packet,
				float64(micros-firstMicros)/1_000_000,
				binary.BigEndian.Uint16(udp), binary.BigEndian.Uint16(udp[2:]), kind, seq,
				binary.LittleEndian.Uint16(decoded[34:36]), decoded[44:48])
			if kind == 0x45 && kind45Shown < 3 {
				size := int(binary.LittleEndian.Uint16(decoded[34:36]))
				fmt.Printf("    data=%x\n", decoded[48:48+size])
				kind45Shown++
			}
			continue
		}
		limit := min(len(decoded), 80)
		fmt.Printf("%03d +%.6fs %d->%d bytes=%d decoded=%x\n", packet,
			float64(micros-firstMicros)/1_000_000,
			binary.BigEndian.Uint16(udp), binary.BigEndian.Uint16(udp[2:]),
			len(payload), decoded[:limit])
	}
}
