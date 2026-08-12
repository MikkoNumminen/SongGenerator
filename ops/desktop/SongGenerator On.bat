@echo off
title SongGenerator - on
rem The edge is a systemd --user unit inside WSL, not a Windows service, even
rem though the process it starts is a Windows one: the pipeline needs the GPU
rem and the Windows venv torch lives in. See the unit's own comments.
wsl -d Ubuntu -e bash -lc "systemctl --user start homelab-songgenerator && sleep 2 && systemctl --user is-active homelab-songgenerator"
echo.
echo Site: https://mikkonumminen.dev/songgenerator
timeout /t 4 >nul
