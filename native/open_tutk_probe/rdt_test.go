package main

import (
	"bytes"
	"testing"
)

func TestRDTPacketRoundTrip(t *testing.T) {
	payload := bytes.Repeat([]byte{0x5a}, 1280)
	raw := makeRDTPacket(0x02, 5, 29, payload, true)
	packet, err := parseRDTPacket(raw)
	if err != nil {
		t.Fatal(err)
	}
	if packet.kind != 0x02 || packet.channel != 5 || packet.seq != 29 || !bytes.Equal(packet.data, payload) {
		t.Fatalf("unexpected RDT packet: kind=%x seq=%d bytes=%d", packet.kind, packet.seq, len(packet.data))
	}
	if raw[16] != 1 || raw[17] != 5 {
		t.Fatalf("application flags = %x", raw[16:20])
	}
}

func TestRDTRejectsOversizedPayload(t *testing.T) {
	raw := makeRDTPacket(0x02, 1, 1, make([]byte, 1281), true)
	if _, err := parseRDTPacket(raw); err == nil {
		t.Fatal("oversized RDT payload was accepted")
	}
}
