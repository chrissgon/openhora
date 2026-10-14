//go:build !(linux && (arm64 || riscv64 || loong64))

package main

import "syscall"

func dup2(oldfd, newfd int) error { return syscall.Dup2(oldfd, newfd) }
