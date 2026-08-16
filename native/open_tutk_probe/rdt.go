package main

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"os"
	"sort"
	"strconv"
	"time"

	"github.com/AlexxIT/go2rtc/pkg/tutk"
)

const (
	meoofDownloadFile         = 8258
	meoofDownloadFileResponse = 8259
	rdtHeaderSize             = 20
	rdtMaxPayload             = 1280
)

var rdtMagic = [4]byte{0x5a, 0x97, 0xc2, 0xf1}

type rdtPacket struct {
	kind    byte
	channel byte
	seq     uint32
	data    []byte
}

func makeRDTPacket(kind, channel byte, seq uint32, data []byte, application bool) []byte {
	packet := make([]byte, rdtHeaderSize+len(data))
	copy(packet, rdtMagic[:])
	packet[4] = kind
	packet[5] = 5
	binary.LittleEndian.PutUint16(packet[6:], uint16(len(data)))
	binary.LittleEndian.PutUint32(packet[8:], seq)
	if application {
		packet[16] = 1
	}
	packet[17] = channel
	copy(packet[rdtHeaderSize:], data)
	return packet
}

func parseRDTPacket(raw []byte) (rdtPacket, error) {
	if len(raw) < rdtHeaderSize || !bytes.Equal(raw[:4], rdtMagic[:]) {
		return rdtPacket{}, errors.New("invalid RDT packet")
	}
	size := int(binary.LittleEndian.Uint16(raw[6:]))
	if size > rdtMaxPayload || rdtHeaderSize+size > len(raw) {
		return rdtPacket{}, errors.New("invalid RDT payload size")
	}
	return rdtPacket{kind: raw[4], channel: raw[17], seq: binary.LittleEndian.Uint32(raw[8:]),
		data: bytes.Clone(raw[rdtHeaderSize : rdtHeaderSize+size])}, nil
}

func readRDTPacket(conn *tutk.Conn) (rdtPacket, error) {
	for {
		raw, err := conn.ReadRDT()
		if err != nil {
			return rdtPacket{}, err
		}
		packet, err := parseRDTPacket(raw)
		if err == nil {
			return packet, nil
		}
	}
}

func writeRDTPacket(conn *tutk.Conn, kind, channel byte, seq uint32, data []byte, application bool) error {
	return conn.WriteRDT(makeRDTPacket(kind, channel, seq, data, application))
}

func createRDT(conn *tutk.Conn) (byte, error) {
	packet, err := readRDTPacket(conn)
	if err != nil {
		return 0, err
	}
	if packet.kind != 0x01 {
		return 0, fmt.Errorf("unexpected RDT create packet 0x%02x", packet.kind)
	}
	channel := packet.channel
	if err := writeRDTPacket(conn, 0x41, channel, packet.seq, nil, false); err != nil {
		return 0, err
	}
	if err := writeRDTPacket(conn, 0x01, 1, 0, nil, false); err != nil {
		return 0, err
	}
	packet, err = readRDTPacket(conn)
	if err != nil {
		return 0, err
	}
	if packet.kind != 0x41 {
		return 0, fmt.Errorf("unexpected RDT create acknowledgement 0x%02x", packet.kind)
	}
	return channel, nil
}

func startRDTKeepalive(conn *tutk.Conn) func() {
	stop := make(chan struct{})
	go func() {
		ticker := time.NewTicker(time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				_ = writeRDTPacket(conn, 0x01, 1, 0, nil, false)
			case <-stop:
				return
			}
		}
	}()
	return func() { close(stop) }
}

func writeRDTData(conn *tutk.Conn, channel byte, seq uint32, data []byte) error {
	if err := writeRDTPacket(conn, 0x02, channel, seq, data, true); err != nil {
		return err
	}
	for {
		packet, err := readRDTPacket(conn)
		if err != nil {
			return err
		}
		if packet.kind == 0x46 && packet.seq == seq {
			return nil
		}
	}
}

func readRDTData(conn *tutk.Conn, channel byte) (rdtPacket, error) {
	packet, err := readRDTApplication(conn)
	if err != nil {
		return rdtPacket{}, err
	}
	if err := writeRDTPacket(conn, 0x46, channel, packet.seq, nil, true); err != nil {
		return rdtPacket{}, err
	}
	return packet, nil
}

func readRDTApplication(conn *tutk.Conn) (rdtPacket, error) {
	for {
		packet, err := readRDTPacket(conn)
		if err != nil {
			return rdtPacket{}, err
		}
		if packet.kind != 0x02 {
			continue
		}
		return packet, nil
	}
}

func writeRDTSelectiveAck(conn *tutk.Conn, channel byte, contiguous uint32,
	pending map[uint32][]byte) error {
	sequences := make([]uint32, 0, len(pending))
	for seq := range pending {
		sequences = append(sequences, seq)
	}
	sort.Slice(sequences, func(i, j int) bool { return sequences[i] < sequences[j] })
	if len(sequences) > 8 {
		sequences = sequences[:8]
	}
	data := make([]byte, 72)
	binary.LittleEndian.PutUint32(data[4:], 1)
	for index, seq := range sequences {
		binary.LittleEndian.PutUint32(data[8+index*8:], seq)
	}
	return writeRDTPacket(conn, 0x45, channel, contiguous, data, true)
}

func closeRDT(conn *tutk.Conn, channel byte) {
	_ = conn.SetDeadline(time.Now().Add(2 * time.Second))
	packet, err := readRDTPacket(conn)
	if err != nil || packet.kind != 0x20 {
		return
	}
	_ = writeRDTPacket(conn, 0x04, channel, packet.seq, nil, false)
	packet, err = readRDTPacket(conn)
	if err == nil && packet.kind == 0x04 {
		_ = writeRDTPacket(conn, 0x60, channel, packet.seq, nil, false)
	}
}

func runDownload(conn *tutk.Conn, source, destination string) error {
	if source == "" || len(source) > 126 || destination == "" {
		return errors.New("invalid download arguments")
	}
	_ = conn.SetDeadline(time.Now().Add(5 * time.Minute))
	responseType, data, err := sendAndReceive(conn, meoofDownloadFile,
		[]byte{1, 0, 0, 0, 0, 0, 0, 0})
	if err != nil {
		return err
	}
	fmt.Printf("download_request=0\ndownload_response_type=%d bytes=%d\n", responseType, len(data))
	if responseType != meoofDownloadFileResponse {
		return fmt.Errorf("unexpected download response %d", responseType)
	}
	_ = conn.SetDeadline(time.Now().Add(5 * time.Minute))
	channel, err := createRDT(conn)
	if err != nil {
		return err
	}
	fmt.Print("rdt_create=0\n")
	stopKeepalive := startRDTKeepalive(conn)
	defer stopKeepalive()

	command := make([]byte, 128)
	command[0] = 1
	copy(command[1:], source)
	if err := writeRDTData(conn, channel, 0, command); err != nil {
		return err
	}
	fmt.Print("rdt_path_write=128\n")
	header, err := readRDTData(conn, channel)
	if err != nil {
		return err
	}
	if len(header.data) < 9 || header.data[0] != 2 {
		return errors.New("invalid RDT file header")
	}
	total, err := strconv.ParseInt(string(bytes.Trim(header.data[1:9], "\x00 ")), 10, 64)
	if err != nil || total < 0 {
		return errors.New("invalid RDT file size")
	}
	fmt.Printf("rdt_header_read=%d cmd=2\nrdt_file_size=%d\n", len(header.data), total)

	clear(command)
	command[0] = 4
	copy(command[1:], "Start")
	if err := writeRDTData(conn, channel, 1, command); err != nil {
		return err
	}
	fmt.Print("rdt_start_write=128\n")
	output, err := os.OpenFile(destination, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	written := int64(0)
	expected := uint32(1)
	pending := make(map[uint32][]byte)
	for written < total {
		packet, err := readRDTApplication(conn)
		if err != nil {
			_ = output.Close()
			return err
		}
		if packet.seq < expected {
			if err := writeRDTPacket(conn, 0x46, channel, packet.seq, nil, true); err != nil {
				_ = output.Close()
				return err
			}
			continue
		}
		pending[packet.seq] = packet.data
		if packet.seq > expected {
			if err := writeRDTSelectiveAck(conn, channel, expected-1, pending); err != nil {
				_ = output.Close()
				return err
			}
			continue
		}
		for {
			chunk, ok := pending[expected]
			if !ok {
				break
			}
			delete(pending, expected)
			remaining := total - written
			if int64(len(chunk)) > remaining {
				chunk = chunk[:remaining]
			}
			n, writeErr := output.Write(chunk)
			written += int64(n)
			if writeErr != nil {
				_ = output.Close()
				return writeErr
			}
			expected++
		}
		if err := writeRDTPacket(conn, 0x46, channel, expected-1, nil, true); err != nil {
			_ = output.Close()
			return err
		}
	}
	if err := output.Close(); err != nil {
		return err
	}
	fmt.Printf("rdt_file_written=%d\n", written)

	clear(command)
	command[0] = 5
	copy(command[1:], "Stop")
	if err := writeRDTData(conn, channel, 2, command); err != nil {
		return err
	}
	closeRDT(conn, channel)
	return nil
}
