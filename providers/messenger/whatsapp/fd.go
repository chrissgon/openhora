package main

import (
	"os"
	"syscall"
)

// reserveProtocol duplicates descriptor 1 for the protocol and points descriptor 1 at standard error, so that a library's
// print can never corrupt a line. It returns the file for the protocol. The duplicate is above 2, so a write to a closed
// pipe returns EPIPE instead of killing the process with SIGPIPE.
func reserveProtocol() (*os.File, error) {
	fd, err := syscall.Dup(1)
	if err != nil {
		return nil, err
	}
	syscall.CloseOnExec(fd)
	if err := dup2(2, 1); err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(fd), "protocol"), nil
}
