package main

import (
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"strconv"
	"time"

	"github.com/AlexxIT/go2rtc/pkg/tutk"
)

const (
	meoofGetStatus          = 20737
	meoofGetStatusResponse  = 20738
	meoofFeed               = 20740
	meoofFeedResponse       = 20741
	meoofFeedPlan           = 20742
	meoofFeedPlanResponse   = 20743
	meoofFeedNotify         = 20747
	meoofRecordList         = 20750
	meoofRecordListResponse = 20751
	planDays                = 8
	planItems               = 30
	planItemSize            = 9
	planDaySize             = planItems*planItemSize + 2
	planWireSize            = planDays*planDaySize + 2
)

func sendAndReceive(conn *tutk.Conn, controlType uint32, payload []byte) (uint32, []byte, error) {
	if err := conn.SetDeadline(time.Now().Add(20 * time.Second)); err != nil {
		return 0, nil, err
	}
	if err := conn.WriteCommand(controlType, payload); err != nil {
		return 0, nil, err
	}
	return conn.ReadCommand()
}

func startVideo(conn *tutk.Conn) error {
	if err := conn.WriteCommand(0xFF, []byte{0, 0}); err != nil {
		return err
	}
	return conn.WriteCommand(0x1FF, make([]byte, 8))
}

func isVideo(header []byte) bool {
	return len(header) > 0 && (header[0] == tutk.CodecH264 || header[0] == tutk.CodecH265)
}

func runRuntimeCommand(conn *tutk.Conn, mode string, args []string) error {
	switch mode {
	case "status":
		return runStatus(conn)
	case "camera", "stream":
		if len(args) != 1 {
			return fmt.Errorf("%s requires an output path", mode)
		}
		return runCamera(conn, args[0], mode == "stream")
	case "events":
		return runEvents(conn)
	case "records":
		return runRecords(conn)
	case "feed-plan":
		_, _, err := requestFeedPlan(conn)
		return err
	case "today-status":
		if len(args) != 4 {
			return errors.New("today-status requires INDEX STATUS HOUR MINUTE")
		}
		values := make([]int, 4)
		for index, raw := range args {
			value, err := strconv.Atoi(raw)
			if err != nil {
				return err
			}
			values[index] = value
		}
		return setTodayPlanStatus(conn, values[0], values[1], values[2], values[3])
	case "verify-plan-write":
		if len(args) != 0 {
			return errors.New("verify-plan-write takes no arguments")
		}
		return verifyPlanWriteNoChange(conn)
	case "feed":
		if len(args) != 2 {
			return errors.New("feed requires LEFT RIGHT")
		}
		left, err := strconv.Atoi(args[0])
		if err != nil {
			return err
		}
		right, err := strconv.Atoi(args[1])
		if err != nil {
			return err
		}
		return runFeed(conn, left, right)
	case "download":
		if len(args) != 2 {
			return errors.New("download requires SOURCE DESTINATION")
		}
		return runDownload(conn, args[0], args[1])
	default:
		return fmt.Errorf("unknown mode %q", mode)
	}
}

func runStatus(conn *tutk.Conn) error {
	responseType, data, err := sendAndReceive(conn, meoofGetStatus, []byte{0})
	if err != nil {
		return err
	}
	fmt.Printf("status_request=0\nstatus_response_type=%d bytes=%d data=%s\n",
		responseType, len(data), hex.EncodeToString(data))
	return nil
}

func runFeed(conn *tutk.Conn, left, right int) error {
	if left < 0 || left > 10 || right < 0 || right > 10 || left+right == 0 {
		return errors.New("feed portions must be 0..10 with a non-zero total")
	}
	payload := []byte{byte(left), byte(right), 1, 0, 0, 0, 0}
	responseType, data, err := sendAndReceive(conn, meoofFeed, payload)
	if err != nil {
		return err
	}
	fmt.Printf("feed_request=0\nfeed_response_type=%d bytes=%d data=%s\n",
		responseType, len(data), hex.EncodeToString(data))
	if responseType != meoofFeedResponse {
		return fmt.Errorf("unexpected feed response %d", responseType)
	}
	return nil
}

func runCamera(conn *tutk.Conn, path string, stream bool) error {
	if stream {
		_ = conn.SetDeadline(time.Time{})
	} else {
		_ = conn.SetDeadline(time.Now().Add(30 * time.Second))
	}
	if err := startVideo(conn); err != nil {
		return err
	}
	output, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	defer output.Close()
	limit := 120
	if stream {
		limit = int(^uint(0) >> 1)
	}
	frames := 0
	for frames < limit {
		header, payload, err := conn.ReadPacket()
		if err != nil {
			return err
		}
		if !isVideo(header) || len(payload) == 0 {
			continue
		}
		// This feeder labels its Annex-B H.264 frames as codec 0x50 even though
		// the generic go2rtc table assigns that value to H.265. Preserve the
		// payload and let the established HA ffmpeg pipeline parse the stream.
		if _, err := output.Write(payload); err != nil {
			return err
		}
		frames++
		if frames <= 5 {
			fmt.Printf("video_frame=%d bytes=%d codec=%d\n", frames, len(payload), header[0])
		}
	}
	fmt.Printf("video_frames=%d\n", frames)
	return nil
}

func runEvents(conn *tutk.Conn) error {
	_ = conn.SetDeadline(time.Time{})
	if err := conn.WriteCommand(meoofGetStatus, []byte{0}); err != nil {
		return err
	}
	refresh := time.NewTicker(20 * time.Second)
	defer refresh.Stop()
	errors := make(chan error, 1)
	go func() {
		for range refresh.C {
			if err := conn.WriteCommand(meoofGetStatus, []byte{0}); err != nil {
				errors <- err
				return
			}
		}
	}()
	for {
		responseType, data, err := conn.ReadCommand()
		if err != nil {
			return err
		}
		select {
		case err := <-errors:
			return err
		default:
		}
		if responseType == meoofGetStatusResponse {
			fmt.Printf("status_response_type=%d bytes=%d data=%s\n",
				responseType, len(data), hex.EncodeToString(data))
			continue
		}
		if responseType != meoofFeedNotify || len(data) == 0 {
			continue
		}
		name := "eat"
		if data[0] == 0 {
			name = "feed"
		}
		fmt.Printf("event=%s type=%d bytes=%d data=%s\n",
			name, data[0], len(data), hex.EncodeToString(data))
	}
}

func runRecords(conn *tutk.Conn) error {
	request := make([]byte, 144)
	now := time.Now()
	month := time.Date(now.Year(), now.Month()-11, 1, 0, 0, 0, 0, now.Location())
	for index := 0; index < 12; index++ {
		binary.LittleEndian.PutUint32(request[index*12:], uint32(month.Year()))
		binary.LittleEndian.PutUint32(request[index*12+4:], uint32(month.Month()))
		month = month.AddDate(0, 1, 0)
	}
	responseType, data, err := sendAndReceive(conn, meoofRecordList, request)
	if err != nil {
		return err
	}
	fmt.Printf("record_list_request=0\nrecord_list_response_type=%d bytes=%d data=%s\n",
		responseType, len(data), hex.EncodeToString(data))
	if responseType != meoofRecordListResponse {
		return fmt.Errorf("unexpected record list response %d", responseType)
	}
	return nil
}
