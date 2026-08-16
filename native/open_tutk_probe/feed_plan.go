package main

import (
	"bytes"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	"github.com/AlexxIT/go2rtc/pkg/tutk"
)

func requestFeedPlan(conn *tutk.Conn) ([]byte, uint32, error) {
	// Read operation. The device accepts the one-byte operation header and
	// returns the full table; avoiding a padded 2178-byte request also avoids
	// IP fragmentation on the open UDP transport.
	request := []byte{0}
	responseType, data, err := sendPlanAndReceive(conn, request)
	if err != nil {
		return nil, responseType, err
	}
	fmt.Printf("feed_plan_request=0\nfeed_plan_response_type=%d bytes=%d data=%s\n",
		responseType, len(data), hex.EncodeToString(data))
	if len(data) < 90 || responseType != meoofFeedPlanResponse || data[1] != 0 {
		return data, responseType, errors.New("invalid feed plan response")
	}
	return data, responseType, nil
}

func sendPlanAndReceive(conn *tutk.Conn, request []byte) (uint32, []byte, error) {
	if err := conn.SetDeadline(time.Now().Add(20 * time.Second)); err != nil {
		return 0, nil, err
	}
	if err := conn.WriteCommand(meoofFeedPlan, request); err != nil {
		return 0, nil, err
	}
	responseType, data, err := conn.ReadCommand()
	if err != nil {
		return responseType, nil, err
	}
	return responseType, data, nil
}

func planItemsFromSize(size int) int {
	if size < 2 || (size-2)%planDays != 0 {
		return 0
	}
	daySize := (size - 2) / planDays
	if daySize < 11 || (daySize-2)%planItemSize != 0 {
		return 0
	}
	items := (daySize - 2) / planItemSize
	if items < 1 || items > planItems {
		return 0
	}
	return items
}

func findTodayPlanItem(response []byte, wantedIndex, expectedHour, expectedMinute int) (int, error) {
	itemCount := planItemsFromSize(len(response))
	if itemCount == 0 || wantedIndex < 1 || wantedIndex > itemCount {
		return 0, errors.New("feed plan item not found")
	}
	daySize := itemCount*planItemSize + 2
	for day := 0; day < planDays; day++ {
		dayOffset := 2 + day*daySize
		if response[dayOffset] != 8 {
			continue
		}
		for item := 0; item < itemCount; item++ {
			itemOffset := dayOffset + 2 + item*planItemSize
			if int(response[itemOffset]) != wantedIndex {
				continue
			}
			if int(response[itemOffset+3]) != expectedHour ||
				int(response[itemOffset+4]) != expectedMinute {
				return 0, errors.New("feed plan time no longer matches")
			}
			return itemOffset + 6, nil
		}
	}
	return 0, errors.New("today feed plan item not found")
}

func setTodayPlanStatus(conn *tutk.Conn, index, status, hour, minute int) error {
	if index < 1 || index > planItems || (status != 0 && status != 1) ||
		hour < 0 || hour > 23 || minute < 0 || minute > 59 {
		return errors.New("invalid today-status arguments")
	}
	current, _, err := requestFeedPlan(conn)
	if err != nil {
		return err
	}
	statusOffset, err := findTodayPlanItem(current, index, hour, minute)
	if err != nil {
		return err
	}
	previous := 0
	if current[statusOffset] == 1 {
		previous = 1
	}
	fmt.Printf("feed_plan_previous_status=%d\n", previous)
	if previous == status {
		fmt.Print("feed_plan_changed=0\nfeed_plan_verified=1\n")
		return nil
	}

	request := make([]byte, len(current))
	request[0] = 1
	copy(request[1:], current[2:])
	request[statusOffset-1] = byte(status)
	responseType, updated, err := sendPlanAndReceive(conn, request)
	if err != nil {
		return err
	}
	fmt.Printf("feed_plan_set_request=0\nfeed_plan_set_response_type=%d bytes=%d data=%s\n",
		responseType, len(updated), hex.EncodeToString(updated))
	if len(updated) != len(current) || responseType != meoofFeedPlanResponse ||
		updated[0] != 1 || updated[1] != 0 {
		return errors.New("feed plan update was rejected")
	}

	verified, _, err := requestFeedPlan(conn)
	if err != nil {
		return err
	}
	verifiedOffset, err := findTodayPlanItem(verified, index, hour, minute)
	if err != nil || (verified[verifiedOffset] == 1) != (status == 1) {
		return errors.New("feed plan update did not verify")
	}
	before := append([]byte(nil), current...)
	after := append([]byte(nil), verified...)
	before[statusOffset], after[verifiedOffset] = 0, 0
	if !bytes.Equal(before, after) {
		return errors.New("feed plan changed outside the selected item")
	}
	fmt.Print("feed_plan_changed=1\nfeed_plan_verified=1\n")
	return nil
}

// verifyPlanWriteNoChange exercises the large, fragmented write path without
// modifying any schedule entry. It is deliberately an internal diagnostic and
// is not exposed through Home Assistant services.
func verifyPlanWriteNoChange(conn *tutk.Conn) error {
	current, _, err := requestFeedPlan(conn)
	if err != nil {
		return err
	}
	request := make([]byte, len(current))
	request[0] = 1
	copy(request[1:], current[2:])
	responseType, updated, err := sendPlanAndReceive(conn, request)
	if err != nil {
		return err
	}
	if len(updated) != len(current) || responseType != meoofFeedPlanResponse ||
		updated[0] != 1 || updated[1] != 0 {
		return errors.New("unchanged feed plan write was rejected")
	}
	verified, _, err := requestFeedPlan(conn)
	if err != nil {
		return err
	}
	if !bytes.Equal(current, verified) {
		return errors.New("unchanged feed plan write altered the schedule")
	}
	fmt.Print("feed_plan_changed=0\nfeed_plan_write_verified=1\n")
	return nil
}
