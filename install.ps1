<#
  install.ps1 - richtet kushim komplett ein (Windows 10/11, PowerShell 5.1 oder neuer).

  Aufruf im Projektordner:
      powershell -ExecutionPolicy Bypass -File .\install.ps1

  Schalter:
      -Check          Nur pruefen, was fehlt. Aendert nichts, laedt nichts.
      -NoPrompt       Keine Rueckfragen (Vault und Stimme werden dann NICHT angelegt).
      -SkipShortcuts  Keine Desktop-Verknuepfungen anlegen.
      -SkipPath       Den Befehl `kushim` NICHT in den Benutzer-PATH eintragen (siehe scripts\add-path.ps1).

  Das Skript ist wiederholbar: Was schon da und geprueft ist, wird uebersprungen.
  Netzwerk nur waehrend der Installation und nur zu: pypi.org (Python-Pakete), github.com
  (Sprecher-Modell, Wake-Word-Modelle), huggingface.co (Whisper, Stimme). Danach arbeitet kushim offline.
  Ein lokales Sprachmodell (Ollama) gibt es nicht mehr: die einzige KI ist Claude Code.
  Vault-Schluessel und Stimmprofil legt NUR du an (Rueckfrage am Ende).
#>
param(
    [switch]$Check,
    [switch]$NoPrompt,
    [switch]$SkipShortcuts,
    [switch]$SkipPath
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$Venv          = Join-Path $Root ".venv"
$Py            = Join-Path $Venv "Scripts\python.exe"
$script:Problems = @()

function Step($t)  { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "   ok: $t" -ForegroundColor Green }
function Info($t)  { Write-Host "   $t" }
function Warn($t)  { Write-Host "   ACHTUNG: $t" -ForegroundColor Yellow; $script:Problems += $t }
function Missing($t) { Write-Host "   FEHLT: $t" -ForegroundColor Yellow; $script:Problems += "Fehlt: $t" }
function Ask($q) {
    if ($NoPrompt -or $Check) { return $false }
    $a = Read-Host "$q (j/N)"
    return ($a -match '^(j|ja|y|yes)$')
}

# ---------------------------------------------------------------- 1. Voraussetzungen
Step "1/7 Voraussetzungen"
$sysPython = $null
foreach ($cand in @(@("py", "-3.12"), @("py", "-3.11"), @("python"))) {
    try {
        $exe = $cand[0]; $args2 = @(); if ($cand.Count -gt 1) { $args2 = $cand[1..($cand.Count - 1)] }
        $v = & $exe @args2 -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -match '^3\.(11|12)$') { $sysPython = @($exe) + $args2; Ok "Python $v ($($cand -join ' '))"; break }
    } catch { }
}
if (-not $sysPython -and -not (Test-Path $Py)) {
    Warn "Python 3.11 oder 3.12 nicht gefunden. Bitte von python.org installieren (Haken bei 'Add to PATH') und das Skript erneut starten."
    if (-not $Check) { exit 1 }
}
try {
    $gpu = (& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>$null)
    if ($LASTEXITCODE -eq 0 -and $gpu) { Ok "NVIDIA GPU: $gpu" } else { throw "none" }
} catch { Warn "Keine NVIDIA-GPU erkannt (nvidia-smi fehlt). kushim ist auf eine NVIDIA-GPU mit mind. 8 GB ausgelegt." }
$free = [math]::Round((Get-PSDrive -Name ($Root.Substring(0,1))).Free / 1GB, 1)
if ($free -lt 15) { Warn "Nur $free GB frei, empfohlen sind mindestens 15 GB." } else { Ok "$free GB frei" }

# ---------------------------------------------------------------- 2. venv
Step "2/7 Python-Umgebung (.venv)"
if (Test-Path $Py) { Ok ".venv vorhanden" }
elseif ($Check) { Missing ".venv" }
else {
    Info "lege .venv an ..."
    & $sysPython[0] @($sysPython[1..($sysPython.Count)] | Where-Object { $_ }) -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "venv konnte nicht angelegt werden" }
    Ok ".venv angelegt"
}

# ---------------------------------------------------------------- 3. Pakete
Step "3/7 Python-Pakete (feste Versionen, von pypi.org)"
if (Test-Path $Py) {
    & $Py -c "import faster_whisper, piper, sherpa_onnx, sentencepiece, sounddevice, openwakeword, sqlcipher3, keyring" 2>$null
    if ($LASTEXITCODE -eq 0) { Ok "alle Pakete importierbar" }
    elseif ($Check) { Missing "Python-Pakete" }
    else {
        Info "installiere Pakete (kann einige Minuten dauern, ca. 2 GB) ..."
        & $Py -m pip install --upgrade pip
        & $Py -m pip install -e ".[dev,voice]"
        if ($LASTEXITCODE -ne 0) { throw "pip install fehlgeschlagen" }
        # openWakeWord ohne Abhaengigkeiten: tflite-runtime hat auf Windows/Python 3.12 keine Wheels, wir nutzen ONNX.
        & $Py -m pip install "openwakeword==0.6.0" --no-deps
        if ($LASTEXITCODE -ne 0) { throw "openwakeword konnte nicht installiert werden" }
        Ok "Pakete installiert"
    }
}

# ---------------------------------------------------------------- 4. Modelle
Step "4/7 Modelle: Whisper, Stimme, Sprecher, Wake Words (geprueft per SHA-256)"
if (Test-Path $Py) {
    if ($Check) { & $Py scripts\fetch_models.py --check; if ($LASTEXITCODE -ne 0) { Missing "Modelle (fetch_models.py ausfuehren)" } }
    else {
        & $Py scripts\fetch_models.py
        if ($LASTEXITCODE -ne 0) { throw "Modell-Download fehlgeschlagen" }
    }
}

# ---------------------------------------------------------------- 5. Icon
Step "5/7 Logo und Icon"
$ico = Join-Path $Root "assets\kushim.ico"
if (Test-Path $ico) { Ok "Icon vorhanden" }
elseif ($Check) { Missing "assets\kushim.ico" }
elseif (Test-Path $Py) { & $Py scripts\make_icon.py; Ok "Icon erzeugt" }

# ---------------------------------------------------------------- 6. Verknuepfungen
Step "6/7 Desktop-Verknuepfungen"
if ($SkipShortcuts) { Info "uebersprungen (-SkipShortcuts)" }
elseif ($Check) { Info "(im Check-Modus nicht angelegt)" }
elseif (Test-Path $Py) {
    $desk = [Environment]::GetFolderPath("Desktop")
    $ws = New-Object -ComObject WScript.Shell
    $defs = @(
        @{ Name = "kushim App.lnk";     Args = "-m kushim.cli app";   Desc = "kushim App öffnen (Oberfläche, startet Sprache und API selbst)"; Icon = $ico; Target = (Join-Path (Split-Path $Py) "pythonw.exe") },
        @{ Name = "kushim start.lnk";    Args = "-m kushim.cli start"; Desc = "Claude Code mit kushim-Channel öffnen und per Stimme sprechen"; Icon = $ico },
        @{ Name = "kushim sprechen.lnk"; Args = "-m kushim.cli talk";  Desc = "kushim sprechen (Wake Word)";                       Icon = $ico },
        @{ Name = "kushim NOTAUS.lnk";   Args = "-m kushim.cli kill";  Desc = "kushim NOTAUS";                                     Icon = "$env:SystemRoot\System32\shell32.dll,131" }
    )
    foreach ($d in $defs) {
        $s = $ws.CreateShortcut((Join-Path $desk $d.Name))
        $s.TargetPath = $(if ($d.Target -and (Test-Path $d.Target)) { $d.Target } else { $Py }); $s.Arguments = $d.Args; $s.WorkingDirectory = $Root
        $s.IconLocation = $d.Icon; $s.Description = $d.Desc; $s.Save()
        Ok "$($d.Name) auf dem Desktop"
    }
}

# Befehl `kushim` im Terminal: nur <Projekt>\bin im PATH des aktuellen Benutzers (kein Administrator, nichts systemweit).
if ($SkipPath) { Info "Befehl 'kushim' im PATH uebersprungen (-SkipPath)" }
elseif ($Check) { & (Join-Path $Root "scripts\add-path.ps1") -Check }
else { & (Join-Path $Root "scripts\add-path.ps1"); Ok "Befehl 'kushim' (neues Terminal oeffnen)" }

# ---------------------------------------------------------------- 7. Vault und Stimme
Step "7/7 Vault und deine Stimme (nur du)"
if (Test-Path $Py) {
    & $Py -m kushim.cli memory info *> $null
    if ($LASTEXITCODE -eq 0) { Ok "Vault vorhanden" }
    elseif ($Check) { Missing "Vault (kushim memory init)" }
    elseif (Ask "Vault jetzt anlegen? Das erzeugt einen Schluessel im Windows-Credential-Manager") {
        & $Py -m kushim.cli memory init
        Write-Host ""
        Write-Host "   WICHTIG: Sichere jetzt den Schluessel in deinem Passwortmanager:" -ForegroundColor Yellow
        Write-Host "   .venv\Scripts\python -m kushim.cli key export"
        Write-Host "   (Ohne Schluessel sind die Daten bei einer Neuinstallation von Windows verloren.)"
    } else { Info "Spaeter: .venv\Scripts\python -m kushim.cli memory init" }

    & $Py -m kushim.cli doctor
    $doctorOk = ($LASTEXITCODE -eq 0)
    if (-not $doctorOk -and -not $Check) {
        & $Py -m kushim.cli voice status 2>$null | Out-Null
        if (Ask "Deine Stimme jetzt einschreiben (10 Absaetze vorlesen, ca. 5 Minuten, Mikrofon noetig)?") { & $Py -m kushim.cli voice enroll }
    }
}

Write-Host ""
if ($script:Problems.Count -gt 0) {
    Write-Host "Fertig mit Hinweisen:" -ForegroundColor Yellow
    $script:Problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
} else { Write-Host "Fertig." -ForegroundColor Green }
Write-Host "Naechste Schritte stehen in der README (Abschnitt 'Erster Start')."
