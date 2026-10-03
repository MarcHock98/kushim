<#
.SYNOPSIS
  Macht `kushim` als Befehl in jedem neuen Terminal verfuegbar (Benutzer-PATH, ohne Administrator).

.DESCRIPTION
  Traegt NUR den Ordner <Projekt>\bin in den PATH des aktuellen Windows-Benutzers ein (HKCU\Environment).
  Dort liegt kushim.cmd, das die venv des Projekts startet. Die venv selbst kommt nicht in den PATH,
  damit python/pip aus der venv nicht deine anderen Programme ueberdecken.
  Wiederholbar: Ist der Eintrag schon da, passiert nichts. Systemweit (alle Benutzer) wird nichts geaendert.

  -Check    Nur anzeigen, ob der Eintrag da ist. Aendert nichts.
  -Remove   Entfernt den Eintrag wieder.
#>
param([switch]$Check, [switch]$Remove)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Bin  = Join-Path $Root "bin"
if (-not (Test-Path (Join-Path $Bin "kushim.cmd"))) { throw "bin\kushim.cmd fehlt: $Bin" }

function Norm($p) { return ([Environment]::ExpandEnvironmentVariables($p)).TrimEnd('\').ToLowerInvariant() }

$key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $true)
try {
    # Rohwert lesen (Variablen wie %USERPROFILE% nicht aufloesen), damit sie beim Schreiben erhalten bleiben.
    $cur   = [string]$key.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    $parts = @($cur -split ';' | Where-Object { $_ -ne "" })
    $has   = $false
    foreach ($p in $parts) { if ((Norm $p) -eq (Norm $Bin)) { $has = $true } }

    if ($Check) {
        if ($has) { Write-Host "ok: $Bin steht im Benutzer-PATH" } else { Write-Host "FEHLT: $Bin steht nicht im Benutzer-PATH" }
        return
    }
    if ($Remove) {
        if (-not $has) { Write-Host "Nichts zu entfernen: $Bin war nicht im PATH."; return }
        $new = @($parts | Where-Object { (Norm $_) -ne (Norm $Bin) })
        $key.SetValue("Path", ($new -join ';'), [Microsoft.Win32.RegistryValueKind]::ExpandString)
        Write-Host "Entfernt: $Bin"
    }
    elseif ($has) {
        Write-Host "ok: $Bin steht schon im Benutzer-PATH"
        return
    }
    else {
        $key.SetValue("Path", (($parts + $Bin) -join ';'), [Microsoft.Win32.RegistryValueKind]::ExpandString)
        Write-Host "Eingetragen: $Bin"
    }
}
finally { $key.Close() }

# Laufende Programme (Explorer, Windows Terminal) ueber die Aenderung informieren, damit NEUE Terminals den PATH sehen.
try {
    Add-Type -Namespace Win32 -Name Native -MemberDefinition @'
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint flags, uint timeout, out UIntPtr result);
'@
    $r = [UIntPtr]::Zero
    [void][Win32.Native]::SendMessageTimeout([IntPtr]0xffff, 0x001A, [UIntPtr]::Zero, "Environment", 2, 5000, [ref]$r)
} catch { }
Write-Host "Oeffne ein NEUES Terminal; dort geht: kushim doctor"
