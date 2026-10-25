@echo off
rem Igual ao iniciar.bat, mas libera o painel para o celular na mesma rede Wi-Fi.
rem Na primeira vez o Windows pergunta se pode liberar no firewall: permita só em "Redes privadas".
call "%~dp0iniciar.bat" --lan
