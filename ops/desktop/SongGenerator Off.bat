@echo off
title SongGenerator - off
rem Stopping the unit is what actually stops it. Killing the Windows process
rem leaves systemd to start another one, which is what happened the first time
rem somebody tried.
wsl -d Ubuntu -e bash -lc "systemctl --user stop homelab-songgenerator && sleep 1 && systemctl --user is-active homelab-songgenerator"
echo.
echo Stopped. The site will say the machine is not answering, which is normal.
timeout /t 4 >nul
