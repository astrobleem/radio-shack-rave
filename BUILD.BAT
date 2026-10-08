@echo off
cl /nologo /c /G0 /AS /O /W3 src\BEAT.C src\DOSSND.C > evidence\BUILD.LOG
if errorlevel 1 goto fail
link /NOI /MAP /CP:4096 BEAT.OBJ+DOSSND.OBJ,runtime\RSRAVE.EXE,evidence\RSRAVE.MAP,,; >> evidence\BUILD.LOG
if errorlevel 1 goto fail
echo Build complete. CD runtime then PLAY.
goto done
:fail
echo Build failed. Read evidence\BUILD.LOG.
:done
