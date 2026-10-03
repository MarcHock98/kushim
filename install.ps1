<#
  install.ps1 - richtet kushim komplett ein (Windows 10/11, PowerShell 5.1 oder neuer).

  Aufruf im Projektordner:
      powershell -ExecutionPolicy Bypass -File .\install.ps1

  Schalter:
      -Check          Nur pruefen, was fehlt. Aendert nichts, laedt nichts.
      -NoPrompt       Keine Rueckfragen (Vault und Stimme werden dann NICHT angelegt).
      -SkipLlm        Ollama-Modell nicht laden.
      -Llm <name>     Anderes Ollama-Modell laden (z. B. qwen3.5:9b) und in config.toml eintragen.
                      Ohne Angabe: das Modell aus config.toml ([llm] model), sonst qwen2.5:7b.
      -SkipShortcuts  Keine Desktop-Verknuepfungen anlegen.

  Das Skript ist wiederholbar: Was schon da und geprueft ist, wird uebersprungen.
  Netzwerk nur waehrend der Installation und nur zu: pypi.org (Python-Pakete), github.com
  (Ollama, Sprecher-Modell, Wake-Word-Modelle), huggingface.co (Whisper, Stimme),
  registry.ollama.ai (LLM). Danach arbeitet kushim offline.
  Vault-Schluessel und Stimmprofil legt NUR du an (Rueckfrage am Ende).
#>
param(
    [switch]$Check,
    [switch]$NoPrompt,
    [switch]$SkipLlm,
    [string]$Llm = "",
    [switch]$SkipShortcuts
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$OllamaVersion = "v0.35.1"
$OllamaUrl     = "https://github.com/ollama/ollama/releases/download/$OllamaVersion/ollama-windows-amd64.zip"
$OllamaSize    = 1471094402
$OllamaSha256  = "dc50b9ca7f9023c86525012632cd1615b093d0407987444a7f62ecab617e8e93"
$LlmModel      = "qwen2.5:7b"
if ($Llm) { $LlmModel = $Llm }
elseif (Test-Path (Join-Path $PSScriptRoot "config.toml")) {
    $m = Select-String -Path (Join-Path $PSScriptRoot "config.toml") -Pattern '^\s*model\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($m) { $LlmModel = $m.Matches[0].Groups[1].Value }
}
if ($LlmModel -notmatch '^[A-Za-z0-9][A-Za-z0-9._/:-]*$' -or $LlmModel -match '\.\.') { throw "Ungueltiger Modellname: $LlmModel" }
$Venv          = Join-Path $Root ".venv"
$Py            = Join-Path $Venv "Scripts\python.exe"
$OllamaExe     = Join-Path $Root "tools\ollama\ollama.exe"
$OllamaModels  = Join-Path $Root "models\ollama"
$LlmParts      = $LlmModel -split ":", 2
$LlmTag        = if ($LlmParts.Count -gt 1) { $LlmParts[1] } else { "latest" }
$LlmPath       = if ($LlmParts[0] -match "/") { $LlmParts[0] } else { "library/" + $LlmParts[0] }
if (($LlmPath -split "/").Count -eq 2 -and $LlmPath -notmatch "^library/") { $LlmPath = "registry.ollama.ai/" + $LlmPath }
elseif ($LlmPath -match "^library/") { $LlmPath = "registry.ollama.ai/" + $LlmPath }
$LlmManifest   = Join-Path $OllamaModels (("manifests/" + $LlmPath + "/" + $LlmTag) -replace "/", "\")
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
Step "1/8 Voraussetzungen"
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
Step "2/8 Python-Umgebung (.venv)"
if (Test-Path $Py) { Ok ".venv vorhanden" }
elseif ($Check) { Missing ".venv" }
else {
    Info "lege .venv an ..."
    & $sysPython[0] @($sysPython[1..($sysPython.Count)] | Where-Object { $_ }) -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "venv konnte nicht angelegt werden" }
    Ok ".venv angelegt"
}

# ---------------------------------------------------------------- 3. Pakete
Step "3/8 Python-Pakete (feste Versionen, von pypi.org)"
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
Step "4/8 Modelle: Whisper, Stimme, Sprecher, Wake Words (geprueft per SHA-256)"
if (Test-Path $Py) {
    if ($Check) { & $Py scripts\fetch_models.py --check; if ($LASTEXITCODE -ne 0) { Missing "Modelle (fetch_models.py ausfuehren)" } }
    else {
        & $Py scripts\fetch_models.py
        if ($LASTEXITCODE -ne 0) { throw "Modell-Download fehlgeschlagen" }
    }
}

# ---------------------------------------------------------------- 5. Ollama
Step "5/8 Ollama (lokales LLM, nur 127.0.0.1)"
if (Test-Path $OllamaExe) { Ok "Ollama vorhanden ($OllamaExe)" }
elseif ($Check) { Missing "Ollama" }
else {
    $zip = Join-Path $Root "tools\ollama.zip"
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "tools") | Out-Null
    Info "lade Ollama $OllamaVersion (1,4 GB) ..."
    & curl.exe -L --fail -sS -o $zip $OllamaUrl
    if ($LASTEXITCODE -ne 0) { throw "Ollama-Download fehlgeschlagen" }
    if ((Get-Item $zip).Length -ne $OllamaSize) { Remove-Item $zip; throw "Ollama-Groesse stimmt nicht" }
    $h = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    if ($h -ne $OllamaSha256) { Remove-Item $zip; throw "Ollama-Pruefsumme stimmt nicht (Datei verworfen)" }
    Expand-Archive -Path $zip -DestinationPath (Join-Path $Root "tools\ollama") -Force
    Remove-Item $zip
    Ok "Ollama entpackt, Pruefsumme stimmt"
}

if ($SkipLlm) { Info "LLM uebersprungen (-SkipLlm)" }
elseif (Test-Path $LlmManifest) { Ok "LLM $LlmModel vorhanden" }
elseif ($Check) { Missing "LLM $LlmModel" }
elseif (Test-Path $OllamaExe) {
    Info "lade $LlmModel (mehrere GB, aus der Ollama-Bibliothek) ..."
    $env:OLLAMA_HOST = "127.0.0.1:11434"; $env:OLLAMA_MODELS = $OllamaModels
    $started = $null
    $alive = $false
    try { Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null; $alive = $true } catch { }
    if (-not $alive) {
        $started = Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden -PassThru
        for ($i = 0; $i -lt 60 -and -not $alive; $i++) {
            Start-Sleep -Milliseconds 500
            try { Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null; $alive = $true } catch { }
        }
    }
    if (-not $alive) { throw "Ollama startet nicht" }
    try { & $OllamaExe pull $LlmModel; if ($LASTEXITCODE -ne 0) { throw "ollama pull fehlgeschlagen" } }
    finally { if ($started) { Stop-Process -Id $started.Id -Force -ErrorAction SilentlyContinue } }
    Ok "LLM geladen"
    if ($Llm -and (Test-Path $Py)) { & $Py -m kushim.cli llm set $LlmModel }
}

# ---------------------------------------------------------------- 6. Icon
Step "6/8 Logo und Icon"
$ico = Join-Path $Root "assets\kushim.ico"
if (Test-Path $ico) { Ok "Icon vorhanden" }
elseif ($Check) { Missing "assets\kushim.ico" }
elseif (Test-Path $Py) { & $Py scripts\make_icon.py; Ok "Icon erzeugt" }

# ---------------------------------------------------------------- 7. Verknuepfungen
Step "7/8 Desktop-Verknuepfungen"
if ($SkipShortcuts) { Info "uebersprungen (-SkipShortcuts)" }
elseif ($Check) { Info "(im Check-Modus nicht angelegt)" }
elseif (Test-Path $Py) {
    $desk = [Environment]::GetFolderPath("Desktop")
    $ws = New-Object -ComObject WScript.Shell
    $defs = @(
        @{ Name = "kushim.lnk";         Args = "-m kushim.cli start"; Desc = "kushim starten (lokale Dienste, nur 127.0.0.1)"; Icon = $ico },
        @{ Name = "kushim sprechen.lnk"; Args = "-m kushim.cli talk";  Desc = "kushim sprechen (Wake Word)";                       Icon = $ico },
        @{ Name = "kushim NOTAUS.lnk";   Args = "-m kushim.cli kill";  Desc = "kushim NOTAUS";                                     Icon = "$env:SystemRoot\System32\shell32.dll,131" }
    )
    foreach ($d in $defs) {
        $s = $ws.CreateShortcut((Join-Path $desk $d.Name))
        $s.TargetPath = $Py; $s.Arguments = $d.Args; $s.WorkingDirectory = $Root
        $s.IconLocation = $d.Icon; $s.Description = $d.Desc; $s.Save()
        Ok "$($d.Name) auf dem Desktop"
    }
}

# ---------------------------------------------------------------- 8. Vault und Stimme
Step "8/8 Vault und deine Stimme (nur du)"
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
