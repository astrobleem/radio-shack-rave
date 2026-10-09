@echo off
set PATH=C:\BIN
set INCLUDE=C:\INCLUDE
set LIB=C:\LIB
D:
call BUILD.BAT
if errorlevel 1 goto fail
cd runtime
RSRAVE ORIGINAL.RBG /TEST
if errorlevel 1 goto fail
copy COREQA.TXT E:\evidence\COREQA.TXT > nul
RSRAVE E:\BAD.RBG /TEST
if errorlevel 3 goto fail
if not errorlevel 2 goto fail
RSRAVE ORIGINAL.RBG /SIMH
if errorlevel 1 goto fail
copy SIMH.TXT E:\evidence\SIMH.TXT > nul
RSRAVE ORIGINAL.RBG /SIMM
if errorlevel 1 goto fail
copy SIMM.TXT E:\evidence\SIMM.TXT > nul
RSRAVE ORIGINAL.RBG /SIMR
if errorlevel 1 goto fail
copy SIMR.TXT E:\evidence\SIMR.TXT > nul
RSRAVE ORIGINAL.RBG /AUTO /SHOT
if errorlevel 1 goto fail
copy AUDIO.TXT E:\evidence\HIT.TXT > nul
copy RUNLOG.TXT E:\evidence\HIT.LOG > nul
copy FRAME.RAW E:\evidence\HIT.RAW > nul
RSRAVE ORIGINAL.RBG /MISS
if errorlevel 1 goto fail
copy AUDIO.TXT E:\evidence\MISS.TXT > nul
copy RUNLOG.TXT E:\evidence\MISS.LOG > nul
RSRAVE ORIGINAL.RBG /AUTO /CALM /SHOT
if errorlevel 1 goto fail
copy AUDIO.TXT E:\evidence\CALM.TXT > nul
copy RUNLOG.TXT E:\evidence\CALM.LOG > nul
copy FRAME.RAW E:\evidence\CALM.RAW > nul
RSRAVE ORIGINAL.RBG /RETRY
if errorlevel 1 goto fail
copy AUDIO.TXT E:\evidence\RETRY.TXT > nul
copy RUNLOG.TXT E:\evidence\RETRY.LOG > nul
RSRAVE ORIGINAL.RBG /SPAM
if errorlevel 1 goto fail
copy AUDIO.TXT E:\evidence\SPAM.TXT > nul
copy RUNLOG.TXT E:\evidence\SPAM.LOG > nul
RSRAVE ORIGINAL.RBG /HESC
if errorlevel 1 goto fail
copy RUNLOG.TXT E:\evidence\ESC.LOG > nul
RSRAVE ORIGINAL.RBG /SPLASH
if errorlevel 1 goto fail
copy SPLASH.LOG E:\evidence\FALLBACK.LOG > nul
copy FALLBACK.RAW E:\evidence\TITLE.RAW > nul
copy SPLASH.RAW E:\evidence\SPLASH.RAW > nul
RSRAVE ORIGINAL.RBG /SSKIP
if errorlevel 1 goto fail
copy SPLASH.LOG E:\evidence\SKIP.LOG > nul
RSRAVE ORIGINAL.RBG /SESC
if errorlevel 1 goto fail
copy SPLASH.LOG E:\evidence\SESC.LOG > nul
RSRAVE ORIGINAL.RBG /SCALM
if errorlevel 1 goto fail
copy SPLASH.LOG E:\evidence\SCALM.LOG > nul
echo DONE>E:\evidence\NATIVE.OK
goto done
:fail
echo FAILED>E:\evidence\NATIVE.OK
:done
exit
