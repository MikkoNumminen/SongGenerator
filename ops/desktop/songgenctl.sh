#!/usr/bin/env bash
# A terminal for the edge, the way ragctl-shell.sh is one for the RAG stack.
#
# Everything here goes through systemd rather than at the process directly.
# The unit supervises a Windows executable over WSL interop, so killing that
# process only gets another one started.

UNIT=homelab-songgenerator

status() {
  printf '\n  unit    : %s\n' "$(systemctl --user is-active $UNIT 2>/dev/null)"
  printf '  edge    : '
  if curl -s -m 3 http://127.0.0.1:8020/health >/dev/null 2>&1; then
    curl -s -m 3 http://127.0.0.1:8020/health
    printf '\n'
  else
    printf 'not answering\n'
  fi
  printf '  site    : https://mikkonumminen.dev/songgenerator\n\n'
}

while true; do
  status
  cat <<'MENU'
  1) start        2) stop         3) restart
  4) follow the log              5) last 50 lines
  q) quit
MENU
  read -rp '  > ' choice
  case "$choice" in
    1) systemctl --user start   $UNIT ;;
    2) systemctl --user stop    $UNIT ;;
    3) systemctl --user restart $UNIT ;;
    4) journalctl --user -u $UNIT -f ;;
    5) journalctl --user -u $UNIT -n 50 --no-pager ;;
    q|Q) exit 0 ;;
    *) printf '  ?\n' ;;
  esac
done
