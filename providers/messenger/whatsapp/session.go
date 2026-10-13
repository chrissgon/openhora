package main

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"

	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	_ "modernc.org/sqlite" // the pure-Go SQLite driver, registered as "sqlite" (no cgo)
)

// The driver's name must start with "sqlite" (whatsmeow picks its SQL dialect from it) and the connection must enable foreign
// keys, or sqlstore.New refuses to start.
const (
	driverName = "sqlite"
	pragmas    = "?_pragma=foreign_keys(1)&_pragma=busy_timeout(5000)"
)

func sessionDSN(path string) (string, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	return (&url.URL{Scheme: "file", Path: abs}).String() + pragmas, nil
}

func sessionExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

// openStore opens (and with create, makes) the session database. The file is made 0600 under the umask 077; an existing
// file with wider access is narrowed.
func openStore(ctx context.Context, path string) (*sqlstore.Container, error) {
	dsn, err := sessionDSN(path)
	if err != nil {
		return nil, err
	}
	container, err := sqlstore.New(ctx, driverName, dsn, newStderrLogger("store"))
	if err != nil {
		return nil, fmt.Errorf("the session database cannot be opened: %w", err)
	}
	if err := os.Chmod(path, 0o600); err != nil && !errors.Is(err, os.ErrNotExist) {
		container.Close()
		return nil, fmt.Errorf("the session file's mode cannot be set: %w", err)
	}
	return container, nil
}

// pairedDevice is the device the session holds, or nil when it holds none (an unpaired or logged-out session).
func pairedDevice(ctx context.Context, container *sqlstore.Container) (*store.Device, error) {
	devices, err := container.GetAllDevices(ctx)
	if err != nil {
		return nil, err
	}
	for _, d := range devices {
		if d.ID != nil {
			return d, nil
		}
	}
	return nil, nil
}

func phoneOf(id *types.JID) string {
	if id == nil {
		return ""
	}
	return id.User
}
