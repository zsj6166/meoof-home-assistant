package main

import "testing"

func TestPlanItemsFromSize(t *testing.T) {
	if got := planItemsFromSize(planWireSize); got != planItems {
		t.Fatalf("planItemsFromSize(%d) = %d, want %d", planWireSize, got, planItems)
	}
	for _, invalid := range []int{0, 1, planWireSize - 1, planWireSize + 1} {
		if got := planItemsFromSize(invalid); got != 0 {
			t.Fatalf("planItemsFromSize(%d) = %d, want 0", invalid, got)
		}
	}
}

func TestFindTodayPlanItem(t *testing.T) {
	response := make([]byte, planWireSize)
	daySize := planItems*planItemSize + 2
	today := 2 + 3*daySize
	response[today] = 8
	item := today + 2 + 4*planItemSize
	response[item] = 5
	response[item+3] = 20
	response[item+4] = 15

	offset, err := findTodayPlanItem(response, 5, 20, 15)
	if err != nil {
		t.Fatal(err)
	}
	if want := item + 6; offset != want {
		t.Fatalf("offset = %d, want %d", offset, want)
	}
	if _, err := findTodayPlanItem(response, 5, 20, 16); err == nil {
		t.Fatal("expected a mismatch error")
	}
}
