package main

import (
	"fmt"
	"net"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/AlexxIT/go2rtc/pkg/tutk"
)

type connectionResult struct {
	host string
	conn *tutk.Conn
}

func connectDevice(auth credentials) (string, *tutk.Conn, error) {
	if host := strings.TrimSpace(os.Getenv("MEOOF_HOST")); host != "" {
		conn, err := tutk.Dial(host, auth.uid, auth.account, auth.password)
		return host, conn, err
	}
	candidates := candidateHosts()
	if len(candidates) == 0 {
		return "", nil, fmt.Errorf("no private IPv4 /24 was found; set MEOOF_HOST")
	}
	result := make(chan connectionResult, 1)
	for _, host := range candidates {
		host := host
		go func() {
			conn, err := tutk.Dial(host, auth.uid, auth.account, auth.password)
			if err != nil {
				return
			}
			select {
			case result <- connectionResult{host: host, conn: conn}:
			default:
				conn.Close()
			}
		}()
	}
	select {
	case item := <-result:
		return item.host, item.conn, nil
	case <-time.After(8 * time.Second):
		return "", nil, fmt.Errorf("no matching device answered on %d candidates", len(candidates))
	}
}

func candidateHosts() []string {
	unique := map[string]struct{}{}
	for _, value := range strings.Split(os.Getenv("MEOOF_CANDIDATES"), ",") {
		if ip := net.ParseIP(strings.TrimSpace(value)).To4(); ip != nil {
			unique[ip.String()] = struct{}{}
		}
	}
	if subnet := strings.TrimSpace(os.Getenv("MEOOF_SUBNET")); subnet != "" {
		if ip, _, err := net.ParseCIDR(subnet); err == nil && ip.To4() != nil {
			addSlash24(unique, ip.To4(), nil)
		}
	}
	if preferred := preferredIPv4(); preferred != nil {
		addSlash24(unique, preferred, preferred)
	} else {
		addrs, _ := net.InterfaceAddrs()
		for _, addr := range addrs {
			ip, _, err := net.ParseCIDR(addr.String())
			if err != nil || ip.To4() == nil || !ip.IsPrivate() {
				continue
			}
			addSlash24(unique, ip.To4(), ip.To4())
		}
	}
	hosts := make([]string, 0, len(unique))
	for host := range unique {
		hosts = append(hosts, host)
	}
	sort.Strings(hosts)
	return hosts
}

func preferredIPv4() net.IP {
	conn, err := net.DialUDP("udp4", nil, &net.UDPAddr{IP: net.IPv4(1, 1, 1, 1), Port: 53})
	if err != nil {
		return nil
	}
	defer conn.Close()
	if addr, ok := conn.LocalAddr().(*net.UDPAddr); ok {
		return addr.IP.To4()
	}
	return nil
}

func addSlash24(values map[string]struct{}, ip, skip net.IP) {
	base := ip.To4()
	if base == nil {
		return
	}
	for last := 1; last < 255; last++ {
		candidate := net.IPv4(base[0], base[1], base[2], byte(last))
		if skip != nil && candidate.Equal(skip) {
			continue
		}
		values[candidate.String()] = struct{}{}
	}
}
