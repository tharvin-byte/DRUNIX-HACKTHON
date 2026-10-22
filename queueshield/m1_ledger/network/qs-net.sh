#!/usr/bin/env bash
# Drunix test-network wrapper (docs/M1_LEDGER.md §3). Run from m1_ledger/ in a WSL2 / Linux shell, never Git-Bash.
# NOT YET RUN: Docker and Go are not installed on the machine that wrote it. Resolve each [VERIFY] on first use
# and append the answer to docs/DEVIATIONS.md.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEDGER="$(dirname "$HERE")"
DRUNIX="${DRUNIX_DIR:-$LEDGER/drunix}"
TN="$DRUNIX/drunix-network/test-network"
CHANNEL="${CHANNEL:-mychannel}"
CC="${CHAINCODE:-queueshield}"
CC_VER="${CC_VER:-1.0}"
CC_SEQ_FILE="$LEDGER/.cc_sequence"
CCENV="npcioss/drunix-ccenv:1.0"            # tag 1.0, not 1.0.0 (pitfall 1)
YB_TIMEOUT_S="${YB_TIMEOUT_S:-300}"

die() { echo "qs-net: $*" >&2; exit 1; }
seq_get() { [[ -f "$CC_SEQ_FILE" ]] && cat "$CC_SEQ_FILE" || echo 1; }

doctor() {
  for t in docker go jq node; do command -v "$t" >/dev/null || die "missing $t"; done
  (( BASH_VERSINFO[0] >= 4 )) || die "bash >= 4 required"
  local free_kb; free_kb=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
  (( free_kb >= 6*1024*1024 )) || echo "qs-net: warning: < 6 GB free RAM (11 containers incl. 2 YugabyteDB)"
  [[ -d "$DRUNIX" ]] || die "no $DRUNIX; run: $0 clone"
  docker image inspect "$CCENV" >/dev/null 2>&1 || docker pull "$CCENV"
  echo "go inside ccenv: $(docker run --rm "$CCENV" go version)"     # [VERIFY] -> pin go.mod / contract-api
}

clone() { git clone https://github.com/npci/drunix.git "$DRUNIX"; echo "pin this commit in m1_ledger/README.md: $(git -C "$DRUNIX" rev-parse HEAD)"; }

build_tools() { (cd "$DRUNIX" && make peer configtxgen configtxlator cryptogen osnadmin) || die "build tools failed (try go install fallback)"; }

wait_yugabyte() {
  local deadline=$(( SECONDS + YB_TIMEOUT_S ))
  for org in org1 org2; do
    until docker exec "yugabyte-$org" yugabyted status >/dev/null 2>&1; do
      (( SECONDS < deadline )) || die "yugabyte-$org not ready after ${YB_TIMEOUT_S}s"
      sleep 5
    done
  done
}

restart_exited() {   # pitfall 2: peers exit once with "connection refused 5433" if YugabyteDB was slow
  for c in lp1.org1 cp.org1 vs1.org1 lp1.org2 cp.org2 vs1.org2 orderer.example.com; do
    if [[ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" == "false" ]]; then docker start "$c"; fi
  done
}

up() {
  (cd "$TN" && ./network.sh up -s yugabyte)
  wait_yugabyte
  restart_exited
  sleep 5
  docker ps --format 'table {{.Names}}\t{{.Status}}'
  local n; n=$(docker ps -q | wc -l)
  (( n >= 11 )) || die "expected 11 running containers, got $n"
}

create_channel() { (cd "$TN" && ./network.sh createChannel -c "$CHANNEL"); }

deploy() {
  local seq; seq=$(seq_get)
  (cd "$LEDGER/chaincode" && go mod vendor)          # build needs no network inside ccenv
  (cd "$TN" && ./network.sh deployCC -c "$CHANNEL" -ccn "$CC" -ccp "$LEDGER/chaincode" -ccl go \
      -ccv "$CC_VER" -ccs "$seq" -ccep "AND('Org1MSP.peer','Org2MSP.peer')")
}

upgrade() { echo $(( $(seq_get) + 1 )) > "$CC_SEQ_FILE"; CC_VER="${CC_VER}.$(seq_get)"; deploy; }

cc() {   # cc invoke|query '<fn>' '<json args array>'
  local op="$1" fn="$2" args="$3" flag="-ccic"
  [[ "$op" == "query" ]] && flag="-ccqc"
  (cd "$TN" && ./network.sh cc "$op" -c "$CHANNEL" -ccn "$CC" "$flag" "{\"Args\":[\"$fn\",${args#[}")
}

sql() { docker exec -it yugabyte-org1 sh -c "PGPASSWORD=yugabyte ysqlsh -h \$(hostname) -U yugabyte -d yugabyte -c \"$1\""; }

status() {
  docker ps --format 'table {{.Names}}\t{{.Status}}'
  for c in $(docker ps --format '{{.Names}}'); do docker logs "$c" 2>&1 | grep -E 'panic|fatal|ERRO' | tail -2 | sed "s/^/$c: /"; done
}

down() { (cd "$TN" && ./network.sh down); rm -f "$LEDGER/../data/ledger_checkpoint.json"; }

bootstrap() { doctor; up; create_channel; deploy; }

cmd="${1:-}"; shift || true
case "$cmd" in
  doctor|clone|up|down|status|bootstrap|deploy|upgrade) "$cmd" ;;
  build-tools) build_tools ;;
  create-channel) create_channel ;;
  invoke) cc invoke "$@" ;;
  query) cc query "$@" ;;
  sql) sql "$@" ;;
  *) echo "usage: $0 {doctor|clone|build-tools|up|create-channel|deploy|upgrade|invoke|query|sql|status|down|bootstrap}"; exit 2 ;;
esac
