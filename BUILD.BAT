@echo off
if "%LIBTANDY%"=="" set LIBTANDY=deps\libtandy
if not exist "%LIBTANDY%\sound\SMF.C" goto nolib
cl /nologo /c /G0 /Gs /AS /W3 /Oe /Ot /On /Ow /I"%LIBTANDY%\include" /I"%LIBTANDY%\sound" src\BEAT.C src\DOSSND.C src\RAVEMID.C "%LIBTANDY%\sound\SMF.C" "%LIBTANDY%\sound\MIDISYN.C" "%LIBTANDY%\sound\INSTR.C" > evidence\BUILD.LOG
if errorlevel 1 goto fail
link /NOI /MAP /CP:4096 BEAT.OBJ+DOSSND.OBJ+RAVEMID.OBJ+SMF.OBJ+MIDISYN.OBJ+INSTR.OBJ,runtime\RSRAVE.EXE,evidence\RSRAVE.MAP,,; >> evidence\BUILD.LOG
if errorlevel 1 goto fail
echo Build complete. Use PLAY CHART.RBG /STREAM SONG.RWS for prepared music, or /MIDI SONG.MID for live parsing.
goto done
:nolib
echo Shared libtandy source not found. Run python tools/fetch_sound_deps.py, or set LIBTANDY to the pinned public libtandy source.
goto done
:fail
echo Build failed. Read evidence\BUILD.LOG.
:done
