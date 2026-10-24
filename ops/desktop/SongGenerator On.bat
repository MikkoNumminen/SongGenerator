@echo off
title SongGenerator - on
rem The edge is a systemd --user unit inside WSL, not a Windows service, even
rem though the process it starts is a Windows one: the pipeline needs the GPU
rem and the Windows venv torch lives in. See the unit's own comments.
wsl -d Ubuntu -e bash -lc "systemctl --user start homelab-songgenerator && sleep 2 && systemctl --user is-active homelab-songgenerator"
echo.
rem The public address is kept in ~/.config/songgenerator.env, not here.
wsl -d Ubuntu -e bash -lc "sed -n 's/^SONGGEN_SITE=/Site: /p' ~/.config/songgenerator.env"
timeout /t 4 >nul
