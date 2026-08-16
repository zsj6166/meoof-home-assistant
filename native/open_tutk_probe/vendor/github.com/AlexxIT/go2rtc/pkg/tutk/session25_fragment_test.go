package tutk

import (
	"bytes"
	"encoding/binary"
	"net"
	"testing"
)

func TestSession25SendIOCtrlChunks(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()

	session := NewSession25(client, make([]byte, 8))
	payload := bytes.Repeat([]byte{0x5a}, 2178)
	chunks := session.SendIOCtrlChunks(20742, payload)
	if len(chunks) != 3 {
		t.Fatalf("got %d chunks, want 3", len(chunks))
	}
	if len(chunks[0]) != 1080 || len(chunks[1]) != 1080 || len(chunks[2]) != 190 {
		t.Fatalf("unexpected wire sizes: %d, %d, %d", len(chunks[0]), len(chunks[1]), len(chunks[2]))
	}

	var complete []byte
	for index, message := range chunks {
		command := message[msgHhrSize:]
		if got := binary.LittleEndian.Uint16(command[10:]); got != uint16(index) {
			t.Errorf("chunk %d sequence = %d", index, got)
		}
		if got := binary.LittleEndian.Uint16(command[12:]); got != 3 {
			t.Errorf("chunk %d total = %d", index, got)
		}
		if got := binary.LittleEndian.Uint16(command[14:]); got != uint16(index) {
			t.Errorf("chunk %d index = %d", index, got)
		}
		if got := binary.LittleEndian.Uint16(command[20:]); got != 0 {
			t.Errorf("chunk %d message ID = %d", index, got)
		}
		size := int(binary.LittleEndian.Uint16(command[16:]))
		complete = append(complete, command[cmdHdrSize25:cmdHdrSize25+size]...)
	}

	if got := binary.LittleEndian.Uint32(complete); got != 20742 {
		t.Fatalf("control type = %d", got)
	}
	if !bytes.Equal(complete[4:], payload) {
		t.Fatal("fragmented payload did not round-trip")
	}
}

func TestSession25SendIOCtrlSingleChunkWireSize(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()

	session := NewSession25(client, make([]byte, 8))
	message := session.SendIOCtrlChunks(20737, []byte{0})[0]
	command := message[msgHhrSize:]
	if got := binary.LittleEndian.Uint16(command[16:]); got != 9 {
		t.Fatalf("single-chunk wire size = %d, want 9", got)
	}
}

func TestSession25ChunkAndMessageSequencesAdvanceIndependently(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()

	session := NewSession25(client, make([]byte, 8))
	first := session.SendIOCtrlChunks(20742, []byte{0})[0][msgHhrSize:]
	fragmented := session.SendIOCtrlChunks(20742, bytes.Repeat([]byte{0}, 2178))
	third := session.SendIOCtrlChunks(20742, []byte{0})[0][msgHhrSize:]

	if got := binary.LittleEndian.Uint16(first[10:]); got != 0 {
		t.Fatalf("first chunk sequence = %d", got)
	}
	if got := binary.LittleEndian.Uint16(first[20:]); got != 0 {
		t.Fatalf("first message ID = %d", got)
	}
	for index, message := range fragmented {
		command := message[msgHhrSize:]
		if got := binary.LittleEndian.Uint16(command[10:]); got != uint16(index+1) {
			t.Errorf("fragment %d chunk sequence = %d", index, got)
		}
		if got := binary.LittleEndian.Uint16(command[20:]); got != 1 {
			t.Errorf("fragment %d message ID = %d", index, got)
		}
	}
	if got := binary.LittleEndian.Uint16(third[10:]); got != 4 {
		t.Fatalf("third chunk sequence = %d", got)
	}
	if got := binary.LittleEndian.Uint16(third[20:]); got != 2 {
		t.Fatalf("third message ID = %d", got)
	}
}
