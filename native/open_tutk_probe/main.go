// Command meoof-open-runtime is an open direct-LAN replacement for the
// proprietary QEMU/Android/TUTK compatibility runtime.
package main

import (
	"encoding/hex"
	"fmt"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/AlexxIT/go2rtc/pkg/tutk"
)

type credentials struct {
	uid      string
	account  string
	password string
}

type probeResult struct {
	host    string
	version string
	remote  string
	detail  string
	err     error
}

func loadCredentials() (credentials, error) {
	value := credentials{
		uid: os.Getenv("MEOOF_UID"), account: os.Getenv("MEOOF_ACCOUNT"),
		password: os.Getenv("MEOOF_PASSWORD"),
	}
	if value.uid == "" || value.account == "" || value.password == "" {
		return value, fmt.Errorf("MEOOF_UID, MEOOF_ACCOUNT and MEOOF_PASSWORD are required")
	}
	return value, nil
}

func runCheck(conn *tutk.Conn, check string) (string, error) {
	if err := conn.SetDeadline(time.Now().Add(15 * time.Second)); err != nil {
		return "", err
	}
	switch check {
	case "handshake":
		return "handshake=ok", nil
	case "status":
		responseType, data, err := sendAndReceive(conn, meoofGetStatus, []byte{0})
		if err != nil {
			return "", err
		}
		return fmt.Sprintf("status_type=%d status_bytes=%d status_data=%s",
			responseType, len(data), hex.EncodeToString(data)), nil
	case "camera":
		if err := startVideo(conn); err != nil {
			return "", err
		}
		frames, payloadBytes := 0, 0
		for frames < 3 {
			header, payload, err := conn.ReadPacket()
			if err != nil {
				return "", err
			}
			if !isVideo(header) || len(payload) == 0 {
				continue
			}
			frames++
			payloadBytes += len(payload)
		}
		return fmt.Sprintf("camera_frames=%d camera_payload_bytes=%d", frames, payloadBytes), nil
	default:
		return "", fmt.Errorf("unknown check %q", check)
	}
}

func runProbe(auth credentials, check string, hosts []string) int {
	results := make(chan probeResult, len(hosts))
	var wg sync.WaitGroup
	for _, host := range hosts {
		host := host
		wg.Add(1)
		go func() {
			defer wg.Done()
			conn, err := tutk.Dial(host, auth.uid, auth.account, auth.password)
			if err != nil {
				results <- probeResult{host: host, err: err}
				return
			}
			defer conn.Close()
			detail, err := runCheck(conn, check)
			if err != nil {
				results <- probeResult{host: host, err: err}
				return
			}
			results <- probeResult{host: host, version: conn.Version(),
				remote: conn.RemoteAddr().String(), detail: detail}
		}()
	}
	go func() { wg.Wait(); close(results) }()
	success := false
	for item := range results {
		if item.err != nil {
			fmt.Printf("FAIL host=%s error=%q\n", item.host, item.err)
			continue
		}
		success = true
		fmt.Printf("OK host=%s remote=%s version=%q %s\n",
			item.host, item.remote, item.version, item.detail)
	}
	if !success {
		return 1
	}
	return 0
}

func main() {
	os.Exit(runMain())
}

func runMain() int {
	auth, err := loadCredentials()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 64
	}
	args := os.Args[1:]
	if len(args) >= 2 && args[0] == "--check" {
		if len(args) < 3 {
			fmt.Fprintln(os.Stderr, "usage: meoof-open-runtime --check handshake|status|camera HOST [HOST ...]")
			return 64
		}
		return runProbe(auth, args[1], args[2:])
	}

	mode := "status"
	commandArgs := args
	if len(args) > 0 {
		mode = args[0]
		commandArgs = args[1:]
	}
	host, conn, err := connectDevice(auth)
	if err != nil {
		fmt.Fprintf(os.Stderr, "device discovery failed: %v\n", err)
		return 12
	}
	defer conn.Close()
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signals)
	go func() {
		<-signals
		// Closing the socket unblocks the active command while Close sends the
		// TUTK session-close frame, so service restarts do not leak camera slots.
		_ = conn.Close()
	}()
	fmt.Printf("resolved_host=%s\ntransport_version=%s\n", host, conn.Version())
	if err := runRuntimeCommand(conn, mode, commandArgs); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 14
	}
	return 0
}
