#!/usr/bin/env bash
# A terminal for the edge, the way ragctl-shell.sh is one for the RAG stack.
#
# Everything here goes through systemd rather than at the process directly.
# The unit supervises a Windows executable over WSL interop, so killing that
# process only gets another one started.

UNIT=homelab-songgenerator

# Windows curl, over interop, deliberately. The unit starts a Windows
# python.exe, so uvicorn binds the Windows loopback; WSL is in the default NAT
# mode here, where localhost is forwarded Windows->WSL and not the other way.
# Asking from inside WSL with the Linux curl reaches nothing and reports the
# edge down whenever it is up, which is the one thing this screen is for. The
# gateway address does not help either: the edge listens on 127.0.0.1 only.
HEALTH=http://127.0.0.1:8020/health

status() {
  printf '\n  unit    : %s\n' "$(systemctl --user is-active $UNIT 2>/dev/null)"
  printf '  edge    : '
  if answer=$(curl.exe -s -m 3 "$HEALTH" 2>/dev/null) && [ -n "$answer" ]; then
    printf '%s\n' "$answer"
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
  # Leaving without the read's exit status was an endless loop with no
  # terminal attached: at EOF the read fails, choice stays empty, the case
  # falls to '?' and the whole menu repaints forever.
  read -rp '  > ' choice || exit 0
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
