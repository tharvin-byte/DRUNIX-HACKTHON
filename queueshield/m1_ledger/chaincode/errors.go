package main

import "fmt"

// Errors are "QS_ERR_<CODE>: detail"; the gateway maps BAD_ARG/FORBIDDEN/NOT_FOUND/CONFLICT/INTERNAL to
// HTTP 400/403/404/409/500 (docs/M1_LEDGER.md §4.4). Details must not contain non-deterministic data.
func qsErr(code, format string, a ...interface{}) error {
	return fmt.Errorf("QS_ERR_%s: %s", code, fmt.Sprintf(format, a...))
}

func errBadArg(f string, a ...interface{}) error    { return qsErr("BAD_ARG", f, a...) }
func errForbidden(f string, a ...interface{}) error { return qsErr("FORBIDDEN", f, a...) }
func errNotFound(f string, a ...interface{}) error  { return qsErr("NOT_FOUND", f, a...) }
func errConflict(f string, a ...interface{}) error  { return qsErr("CONFLICT", f, a...) }
func errInternal(f string, a ...interface{}) error  { return qsErr("INTERNAL", f, a...) }
